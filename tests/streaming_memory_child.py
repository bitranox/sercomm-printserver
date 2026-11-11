"""Child process of the streaming memory test: send big file jobs, report peak memory growth.

Run as ``python -m streaming_memory_child`` with ``tests`` as the working directory and ``src``
on ``PYTHONPATH``; prints one JSON object mapping ``<transport>-<MiB>`` to the growth of the
peak resident set (``VmHWM``) in KiB while that job was sent. Linux only: the peak is reset
through ``/proc/self/clear_refs`` before each job, so the import peak and the previous job do
not hide this one. ``ru_maxrss`` cannot be reset, which is why it is not used.

The sinks discard what they read into one fixed buffer, so the only memory that can grow with
the job is the sender's.
"""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
from pathlib import Path
from typing import Final

from sercomm_printserver.adapters.lpd import LpdClient
from sercomm_printserver.adapters.raw import RawPrinter
from sercomm_printserver.domain.endpoint import DeviceEndpoint, PrintJob
from sercomm_printserver.domain.print_data import PrintData

_MIB: Final = 1024 * 1024
_SIZES_MIB: Final = (64, 128)
_BUFFER_SIZE: Final = 64 * 1024
_TIMEOUT: Final = 60.0


def _status_kib(field: str) -> int:
    for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
        if line.startswith(f"{field}:"):
            return int(line.split()[1])
    raise RuntimeError(f"/proc/self/status has no {field}")


def _discard_until_eof(conn: socket.socket, buffer: memoryview, limit: int | None = None) -> int:
    """Read and drop bytes until end of stream, or until ``limit`` bytes; return the count."""
    total = 0
    while limit is None or total < limit:
        want = len(buffer) if limit is None else min(len(buffer), limit - total)
        count = conn.recv_into(buffer, want)
        if count == 0:
            break
        total += count
    return total


def _read_line(conn: socket.socket) -> bytes:
    line = bytearray()
    while not line.endswith(b"\n"):
        byte = conn.recv(1)
        if not byte:
            break
        line += byte
    return bytes(line)


class _Sink:
    """One-connection loopback server run in a thread."""

    def __init__(self, *, lpd: bool) -> None:
        self._lpd = lpd
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port: int = self._listener.getsockname()[1]
        self._buffer = memoryview(bytearray(_BUFFER_SIZE))
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        conn, _ = self._listener.accept()
        with conn:
            if self._lpd:
                self._lpd_session(conn)
            else:
                _discard_until_eof(conn, self._buffer)
        self._listener.close()

    def _lpd_session(self, conn: socket.socket) -> None:
        _read_line(conn)  # receive-job command
        conn.sendall(b"\x00")
        while header := _read_line(conn):
            conn.sendall(b"\x00")
            count = int(header[1:].split(b" ", 1)[0])
            _discard_until_eof(conn, self._buffer, count + 1)  # the file and its 0x00
            conn.sendall(b"\x00")

    def join(self) -> None:
        self._thread.join(_TIMEOUT)


def _sparse_file(directory: Path, size: int) -> Path:
    # Sparse: written in no time, read back as zeros at full length.
    path = directory / f"job-{size}.prn"
    with path.open("wb") as stream:
        stream.truncate(size)
    return path


def _send(path: Path, *, lpd: bool) -> None:
    sink = _Sink(lpd=lpd)
    data = PrintData.from_path(path)
    if lpd:
        endpoint = DeviceEndpoint(host="127.0.0.1", lpd_port=sink.port, timeout=_TIMEOUT)
        LpdClient().submit(endpoint, "L1", PrintJob(data=data))
    else:
        RawPrinter().send(DeviceEndpoint(host="127.0.0.1", timeout=_TIMEOUT), sink.port, data)
    sink.join()


def _measure(path: Path, *, lpd: bool) -> int:
    Path("/proc/self/clear_refs").write_text("5", encoding="ascii")
    before = _status_kib("VmRSS")
    _send(path, lpd=lpd)
    return _status_kib("VmHWM") - before


def main() -> int:
    """Send every size by RAW and LPD; print the peak growth of each as one JSON object."""
    growth: dict[str, int] = {}
    with tempfile.TemporaryDirectory() as scratch:
        for size in _SIZES_MIB:
            path = _sparse_file(Path(scratch), size * _MIB)
            for lpd in (False, True):
                growth[f"{'lpd' if lpd else 'raw'}-{size}"] = _measure(path, lpd=lpd)
            path.unlink()
    sys.stdout.write(json.dumps(growth) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
