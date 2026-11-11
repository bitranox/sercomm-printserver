"""PrintData: one print job's bytes, handed out in pieces of at most 64 KiB, whatever the source."""

from __future__ import annotations

import io
import operator
from typing import TYPE_CHECKING

import pytest
from print_sources import pipe_with
from pydantic import ValidationError

from sercomm_printserver import PrintData as ExportedPrintData
from sercomm_printserver.domain.endpoint import PrintJob
from sercomm_printserver.domain.print_data import PIECE_SIZE, PrintData

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.os_agnostic

#: More than two pieces, and not a multiple of the piece size.
_JOB = bytes(range(256)) * 600


def _joined(data: PrintData) -> bytes:
    return b"".join(data.pieces())


def _piece_sizes(data: PrintData) -> list[int]:
    return [len(piece) for piece in data.pieces()]


@pytest.fixture
def pipe_job() -> Iterator[io.BufferedReader]:
    with pipe_with(_JOB) as reader:
        yield reader


def test_the_package_root_exports_print_data() -> None:
    assert ExportedPrintData is PrintData


def test_bytes_have_their_size_and_come_back_in_pieces_of_at_most_64_kib() -> None:
    data = PrintData.of(_JOB)

    assert data.size == len(_JOB)
    assert _joined(data) == _JOB
    assert max(_piece_sizes(data)) == PIECE_SIZE == 64 * 1024


def test_bytes_can_be_read_again() -> None:
    data = PrintData.of(_JOB)

    assert _joined(data) == _joined(data) == _JOB


def test_a_path_takes_its_size_from_the_file_and_reads_it_afresh_each_time(tmp_path: Path) -> None:
    path = tmp_path / "job.prn"
    path.write_bytes(_JOB)
    data = PrintData.from_path(path)
    first = _joined(data)
    path.write_bytes(b"changed")

    assert data.size == len(_JOB)
    assert first == _JOB
    assert _joined(data) == b"changed"
    assert max(_piece_sizes(PrintData.from_path(tmp_path / "job.prn"))) <= PIECE_SIZE


def test_a_path_is_not_opened_before_its_pieces_are_read(tmp_path: Path) -> None:
    path = tmp_path / "job.prn"
    path.write_bytes(b"x")
    data = PrintData.from_path(path)
    path.unlink()

    with pytest.raises(FileNotFoundError):
        _joined(data)


def test_a_missing_path_is_refused_when_its_size_is_read(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        PrintData.from_path(tmp_path / "absent.prn")


def test_a_regular_file_stream_counts_its_size_from_the_current_position(tmp_path: Path) -> None:
    path = tmp_path / "job.prn"
    path.write_bytes(_JOB)
    with path.open("rb") as stream:
        stream.seek(10)
        data = PrintData.from_stream(stream)

        assert data.size == len(_JOB) - 10
        assert _joined(data) == _JOB[10:]


def test_a_pipe_has_no_size_and_yields_every_byte_in_pieces(pipe_job: io.BufferedReader) -> None:
    data = PrintData.from_stream(pipe_job)

    assert data.size is None
    pieces = list(data.pieces())
    assert b"".join(pieces) == _JOB
    assert max(len(piece) for piece in pieces) <= PIECE_SIZE


def test_a_stream_without_a_file_number_has_no_size() -> None:
    data = PrintData.from_stream(io.BytesIO(b"abc"))

    assert data.size is None
    assert _joined(data) == b"abc"


def test_a_stream_can_be_read_only_once(pipe_job: io.BufferedReader) -> None:
    data = PrintData.from_stream(pipe_job)
    _joined(data)

    with pytest.raises(RuntimeError, match="already consumed"):
        data.pieces()


def test_bytes_read_counts_what_the_stream_handed_out(pipe_job: io.BufferedReader) -> None:
    data = PrintData.from_stream(pipe_job)
    assert data.bytes_read == 0

    _joined(data)

    assert data.bytes_read == len(_JOB)


def test_unless_empty_answers_from_the_size_without_reading(tmp_path: Path) -> None:
    path = tmp_path / "job.prn"
    path.write_bytes(b"x")
    data = PrintData.from_path(path)
    path.unlink()

    assert data.unless_empty() is data
    assert PrintData.of(b"").unless_empty() is None


def test_unless_empty_finds_an_empty_pipe() -> None:
    with pipe_with(b"") as reader:
        assert PrintData.from_stream(reader).unless_empty() is None


def test_unless_empty_keeps_the_first_piece_of_a_pipe_it_read(pipe_job: io.BufferedReader) -> None:
    data = PrintData.from_stream(pipe_job)
    held = data.unless_empty()

    assert held is not None
    assert held.size is None
    assert _joined(held) == _JOB
    assert data.bytes_read == len(_JOB)


def test_in_memory_data_equals_its_bytes_and_hashes_like_them() -> None:
    assert PrintData.of(b"abc") == PrintData.of(b"abc")
    assert PrintData.of(b"abc") == b"abc"
    assert operator.eq(b"abc", PrintData.of(b"abc"))  # bytes first: the reflected comparison
    assert PrintData.of(b"abc") != PrintData.of(b"abd")
    assert hash(PrintData.of(b"abc")) == hash(b"abc")


def test_a_stream_equals_only_itself_since_comparing_would_consume_it(pipe_job: io.BufferedReader) -> None:
    data = PrintData.from_stream(pipe_job)

    assert data == data  # noqa: PLR0124 - identity is the whole rule being pinned
    assert data != PrintData.of(_JOB)
    assert data != _JOB
    assert data.bytes_read == 0


def test_the_repr_names_the_source_and_size_but_never_the_content(tmp_path: Path) -> None:
    path = tmp_path / "job.prn"
    path.write_bytes(b"secret")

    assert repr(PrintData.of(b"secret")) == "PrintData.of(<6 bytes>)"
    assert repr(PrintData.from_path(path)) == f"PrintData.from_path({str(path)!r}, size=6)"
    assert repr(PrintData.from_stream(io.BytesIO(b"secret"))) == "PrintData.from_stream(<BytesIO>, size=None)"


# PrintJob ------------------------------------------------------------------


def test_a_print_job_still_takes_plain_bytes() -> None:
    job = PrintJob(data=b"hello\r\n\f", name="greeting")

    assert isinstance(job.data, PrintData)
    assert job.data == b"hello\r\n\f"
    assert job == PrintJob(data=b"hello\r\n\f", name="greeting")


def test_a_print_job_takes_print_data_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "job.prn"
    path.write_bytes(_JOB)
    data = PrintData.from_path(path)

    assert PrintJob(data=data).data is data


def test_a_print_job_validated_from_a_mapping_wraps_bytes() -> None:
    job = PrintJob.model_validate({"data": b"x", "name": "page"})

    assert job.data == PrintData.of(b"x")


def test_a_print_job_refuses_data_that_is_not_bytes() -> None:
    with pytest.raises(ValidationError, match="data"):
        PrintJob.model_validate({"data": 5})
