"""A file job is streamed: sending it grows peak memory by a bounded amount, not by its size.

Measured in a child process (see ``streaming_memory_child``) through the real RawPrinter and
LpdClient to loopback sinks, at two job sizes. Holding the job whole would grow the peak by
about its size (64 and 128 MiB); streaming holds one 64 KiB piece plus socket buffers.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.os_linux

_TESTS_DIR: Final = Path(__file__).resolve().parent
_SRC_DIR: Final = _TESTS_DIR.parent / "src"
#: Far below the smallest job (64 MiB), far above one piece plus socket and allocator slack.
_MAX_GROWTH_KIB: Final = 16 * 1024


@pytest.fixture(scope="module")
def growth_kib() -> dict[str, int]:
    existing = os.environ.get("PYTHONPATH", "")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, (str(_SRC_DIR), existing)))}
    completed = subprocess.run(
        [sys.executable, "-m", "streaming_memory_child"],
        cwd=_TESTS_DIR,
        env=env,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    measured: dict[str, int] = json.loads(completed.stdout)
    return measured


def test_every_transport_and_size_was_measured(growth_kib: dict[str, int]) -> None:
    assert set(growth_kib) == {"raw-64", "raw-128", "lpd-64", "lpd-128"}


@pytest.mark.parametrize("job", ["raw-64", "raw-128", "lpd-64", "lpd-128"])
def test_sending_a_file_job_grows_peak_memory_far_less_than_the_job(growth_kib: dict[str, int], job: str) -> None:
    assert growth_kib[job] < _MAX_GROWTH_KIB, growth_kib


def test_peak_memory_does_not_grow_with_the_job_size(growth_kib: dict[str, int]) -> None:
    # Doubling the job must not double the growth; a held job would add 64 MiB here.
    for transport in ("raw", "lpd"):
        assert growth_kib[f"{transport}-128"] - growth_kib[f"{transport}-64"] < _MAX_GROWTH_KIB, growth_kib
