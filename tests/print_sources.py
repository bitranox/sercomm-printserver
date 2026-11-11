"""Print-data sources for the streaming tests: a real OS pipe, as a shell pipeline hands one over."""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import io


def pipe_with(content: bytes) -> io.BufferedReader:
    """Return the read end of an OS pipe that delivers ``content`` and then end of file.

    The writer runs in a thread, so content larger than the pipe buffer fits; a reader closed
    before the end makes the writer stop quietly.
    """
    read_fd, write_fd = os.pipe()

    def write() -> None:
        view = memoryview(content)
        try:
            while view:
                view = view[os.write(write_fd, view) :]
        except BrokenPipeError:
            pass  # the test closed the reader without reading everything, which it may
        finally:
            os.close(write_fd)

    threading.Thread(target=write, daemon=True).start()
    return os.fdopen(read_fd, "rb")


__all__ = ["pipe_with"]
