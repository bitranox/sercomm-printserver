"""The bytes of one print job, handed out piece by piece so a job never sits in memory whole.

A parallel-port printer has no slow link behind it, so a job of hundreds of megabytes is a real
case. Holding it as one ``bytes`` costs its whole size in memory, once per job. ``PrintData``
reads its source in pieces of at most :data:`PIECE_SIZE` bytes instead, so a send holds one piece
at a time whatever the source is.

Three sources, and what each can promise:

* bytes already in memory: the size is known and the pieces can be read any number of times;
* a file by path: the size comes from the file system when the data is built, and the file is
  opened afresh on every :meth:`PrintData.pieces` call, so the data can be read again;
* an open stream (stdin, a pipe, an open file): readable once. A stream on a regular file knows
  its size (the file's size minus the current position); a pipe does not, so ``size`` is None.

A file can change between the moment its size was read and the moment it is sent. ``PrintData``
does not hide that: the size stays what was announced, and a sender that relies on it (LPD puts
the size in front of the data) compares it with what the pieces actually delivered.

Standard library only: the domain layer must not depend on a framework.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import IO, TYPE_CHECKING, Final, Protocol, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Generator

#: The largest piece :meth:`PrintData.pieces` hands out. A send of one piece is what bounds a
#: send timeout to a peer that stopped reading, so it also stays well under the size Windows
#: accepts whole into its send buffer.
PIECE_SIZE: Final = 64 * 1024

Piece: TypeAlias = "bytes | memoryview"
"""One piece of print data: at least one and at most :data:`PIECE_SIZE` bytes."""

_Pieces: TypeAlias = "Generator[Piece, None, None]"


class _Source(Protocol):
    def pieces(self) -> _Pieces:
        """Return a generator over the source's bytes; may refuse at once (single-use sources)."""
        ...

    def in_memory(self) -> bytes | None:
        """The bytes, when they are held in memory; None for a file or a stream."""
        ...

    def describe(self) -> str:
        """The constructor call that built the data, without its content."""
        ...


class _BytesSource:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def pieces(self) -> _Pieces:
        return self._slices()

    def _slices(self) -> _Pieces:
        view = memoryview(self._data)
        for start in range(0, len(view), PIECE_SIZE):
            yield view[start : start + PIECE_SIZE]

    def in_memory(self) -> bytes | None:
        return self._data

    def describe(self) -> str:
        return f"<{len(self._data)} bytes>"


class _PathSource:
    def __init__(self, path: Path) -> None:
        self._path = path

    def pieces(self) -> _Pieces:
        return self._read()

    def _read(self) -> _Pieces:
        # Opened here, at the first piece, so building the data holds no file handle and a
        # second run reads the file as it is then.
        with self._path.open("rb") as stream:
            yield from _read_stream(stream)

    def in_memory(self) -> bytes | None:
        return None

    def describe(self) -> str:
        return repr(str(self._path))


class _StreamSource:
    def __init__(self, stream: IO[bytes]) -> None:
        self._stream = stream
        self._consumed = False

    def pieces(self) -> _Pieces:
        if self._consumed:
            raise RuntimeError(
                "this print data reads a stream, which was already consumed; build a new PrintData to send it again"
            )
        self._consumed = True
        return _read_stream(self._stream)

    def in_memory(self) -> bytes | None:
        return None

    def describe(self) -> str:
        return f"<{type(self._stream).__name__}>"


class _HeldSource:
    """A single-use source whose first piece was already read, to learn it was not empty."""

    def __init__(self, first: Piece, rest: _Pieces, origin: _Source) -> None:
        self._first: Piece | None = first
        self._rest = rest
        self._origin = origin

    def pieces(self) -> _Pieces:
        first = self._first
        if first is None:
            raise RuntimeError(
                "this print data reads a stream, which was already consumed; build a new PrintData to send it again"
            )
        self._first = None
        return self._replay(first)

    def _replay(self, first: Piece) -> _Pieces:
        try:
            yield first
            yield from self._rest
        finally:
            self._rest.close()

    def in_memory(self) -> bytes | None:
        return None

    def describe(self) -> str:
        return self._origin.describe()


def _read_stream(stream: IO[bytes]) -> _Pieces:
    while piece := stream.read(PIECE_SIZE):
        yield piece


def _regular_file_size(stream: IO[bytes]) -> int | None:
    """Bytes left in ``stream`` when it reads a regular file; None for a pipe, socket or tty."""
    try:
        status = os.fstat(stream.fileno())
        if not stat.S_ISREG(status.st_mode):
            return None
        return max(0, status.st_size - stream.tell())
    except (OSError, ValueError):
        # OSError covers io.UnsupportedOperation (an in-memory stream has no file number);
        # ValueError a closed stream.
        return None


class PrintData:
    """The bytes of one print job, read from their source in pieces of at most 64 KiB.

    Build it with :meth:`of`, :meth:`from_path` or :meth:`from_stream`. Data held in memory
    equals other in-memory data and plain ``bytes`` with the same content (and hashes like those
    bytes); data read from a file or a stream equals only itself, because comparing would read
    it.

    Example:
        >>> data = PrintData.of(b"hello\\f")
        >>> data.size, b"".join(data.pieces()), data == b"hello\\f"
        (6, b'hello\\x0c', True)
        >>> data
        PrintData.of(<6 bytes>)
    """

    __slots__ = ("_bytes_read", "_size", "_source")

    def __init__(self, source: _Source, *, size: int | None) -> None:
        """Use :meth:`of`, :meth:`from_path` or :meth:`from_stream`; ``source`` is internal."""
        self._source = source
        self._size = size
        self._bytes_read = 0

    @classmethod
    def of(cls, data: bytes) -> PrintData:
        """Wrap bytes already in memory; no copy is made.

        Example:
            >>> PrintData.of(b"abc").size
            3
        """
        return cls(_BytesSource(data), size=len(data))

    @classmethod
    def from_path(cls, path: str | os.PathLike[str]) -> PrintData:
        """Read the file at ``path``; its size is taken now, its bytes when the pieces are read.

        A path that is not a regular file (a FIFO, a device) has no size and reads only once.

        Raises:
            OSError: The file cannot be found or examined (``FileNotFoundError`` and the like).
        """
        resolved = Path(path)
        status = resolved.stat()
        size = status.st_size if stat.S_ISREG(status.st_mode) else None
        return cls(_PathSource(resolved), size=size)

    @classmethod
    def from_stream(cls, stream: IO[bytes], *, size: int | None = None) -> PrintData:
        """Read an open binary stream once, from its current position to its end.

        Args:
            stream: Read with ``read(PIECE_SIZE)`` until it returns no bytes; never closed here.
            size: The byte count, for a caller that knows it while the stream cannot tell;
                None takes it from the stream: a regular file reports what is left past the
                current position, anything else leaves the size unknown.

        Example:
            >>> import io
            >>> PrintData.from_stream(io.BytesIO(b"abc")).size is None
            True
        """
        known = size if size is not None else _regular_file_size(stream)
        return cls(_StreamSource(stream), size=known)

    @property
    def size(self) -> int | None:
        """The number of bytes announced for the job; None for a stream that cannot tell (a pipe)."""
        return self._size

    @property
    def bytes_read(self) -> int:
        """How many bytes the most recent :meth:`pieces` run has handed out so far."""
        return self._bytes_read

    def pieces(self) -> _Pieces:
        """Return the job's bytes as pieces of 1 to :data:`PIECE_SIZE` bytes, read one at a time.

        Raises:
            RuntimeError: The data reads a stream and was already read once.
            OSError: Reading the file or the stream failed (raised by the generator).
        """
        source_pieces = self._source.pieces()
        self._bytes_read = 0
        return self._counted(source_pieces)

    def _counted(self, source_pieces: _Pieces) -> _Pieces:
        try:
            for piece in source_pieces:
                self._bytes_read += len(piece)
                yield piece
        finally:
            source_pieces.close()

    def unless_empty(self) -> PrintData | None:
        """Return data that yields the same bytes, or None when there are none.

        Data with a known size answers from the size and returns itself without reading. A
        stream with no size reads its first piece, and the data returned yields that piece
        first; the stream is then consumed for this object, so send the returned data.

        Example:
            >>> PrintData.of(b"").unless_empty() is None
            True
        """
        if self._size is not None:
            return self if self._size > 0 else None
        source_pieces = self.pieces()
        first = next(source_pieces, None)
        if first is None:
            return None
        return PrintData(_HeldSource(first, source_pieces, self._source), size=None)

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        if isinstance(other, PrintData):
            mine, theirs = self._source.in_memory(), other._source.in_memory()
            return mine is not None and theirs is not None and mine == theirs
        if isinstance(other, (bytes, bytearray, memoryview)):
            mine = self._source.in_memory()
            return mine is not None and mine == other
        return NotImplemented

    def __hash__(self) -> int:
        mine = self._source.in_memory()
        return hash(mine) if mine is not None else object.__hash__(self)

    def __repr__(self) -> str:
        if isinstance(self._source, _BytesSource):
            return f"PrintData.of({self._source.describe()})"
        kind = "from_path" if isinstance(self._source, _PathSource) else "from_stream"
        return f"PrintData.{kind}({self._source.describe()}, size={self._size})"


__all__ = ["PIECE_SIZE", "Piece", "PrintData"]
