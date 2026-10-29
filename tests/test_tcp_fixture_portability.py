"""No test may leave a TCP socket bound but not listening while it is in use.

On macOS a SYN to a port that is bound but not listening gets no reset at all, so the client's
connect hangs until its timeout; Linux and Windows refuse it. A fixture built that way to mean
"a refusing port" therefore tests a timeout on the macOS CI cell, and an assertion loose enough
to accept "could not be reached" hides that (it happened twice in this suite). A port nothing
holds is refused everywhere: take one from ``fake_lpd_server.closed_port()``, which binds,
reads the number and releases it.

The rule, checked on every file in ``tests/`` by walking its syntax tree: a TCP socket (one
created by ``socket.socket`` without ``SOCK_DGRAM``) that is bound must, in the same function,
also be listened on or closed, or be bound inside a ``with`` block that does nothing after the
bind but read the port number. ``socket.create_server`` always listens and UDP sockets never
do, so neither is checked.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.os_agnostic

_TESTS = Path(__file__).resolve().parent


def _is_tcp_socket_call(node: ast.AST | None) -> bool:
    if not (isinstance(node, ast.Call) and ast.unparse(node.func) == "socket.socket"):
        return False
    return "SOCK_DGRAM" not in ast.unparse(node)


def _tcp_targets(function: ast.AST) -> set[str]:
    """Names (``probe``, ``self._listener``) bound to a TCP socket inside ``function``."""
    targets: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and _is_tcp_socket_call(node.value):
            targets.update(ast.unparse(target) for target in node.targets)
        elif isinstance(node, ast.withitem) and _is_tcp_socket_call(node.context_expr) and node.optional_vars:
            targets.add(ast.unparse(node.optional_vars))
    return targets


def _calls(function: ast.AST, target: str, method: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == method
        and ast.unparse(node.func.value) == target
        for node in ast.walk(function)
    )


def _only_reads_the_port(statements: list[ast.stmt]) -> bool:
    return all(
        isinstance(statement, (ast.Assign, ast.AnnAssign, ast.Return))
        and statement.value is not None
        and "getsockname" in ast.unparse(statement.value)
        for statement in statements
    )


def _released_inside_with(function: ast.AST, target: str) -> bool:
    """True when ``target`` is bound in a ``with`` block whose remaining body only reads the port."""
    for node in ast.walk(function):
        if not isinstance(node, ast.With):
            continue
        if not any(item.optional_vars is not None and ast.unparse(item.optional_vars) == target for item in node.items):
            continue
        body = node.body
        if body and ast.unparse(body[0]).startswith(f"{target}.bind(") and _only_reads_the_port(body[1:]):
            return True
    return False


def unsafe_binds(source: str, filename: str = "<source>") -> list[str]:
    """Return ``file:line target`` for every TCP bind that breaks the rule in ``source``."""
    tree = ast.parse(source, filename=filename)
    findings: list[str] = []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for target in sorted(_tcp_targets(function)):
            if not _calls(function, target, "bind"):
                continue
            if _calls(function, target, "listen") or _calls(function, target, "close"):
                continue
            if _released_inside_with(function, target):
                continue
            line = next(
                node.lineno
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "bind"
                and ast.unparse(node.func.value) == target
            )
            findings.append(f"{filename}:{line} {target}")
    return findings


_UNSAFE = """
def test_refused():
    with socket.socket() as closed_port:
        closed_port.bind(("127.0.0.1", 0))
        port = closed_port.getsockname()[1]
        connect_to(port)
"""

_SAFE = """
def released():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])

def listener():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)

def reserved():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

def udp():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        serve(sock)
"""


def test_the_detector_flags_a_bound_socket_held_open_without_listening() -> None:
    assert unsafe_binds(_UNSAFE) == ["<source>:4 closed_port"]


def test_the_detector_passes_released_listening_closed_and_udp_sockets() -> None:
    assert unsafe_binds(_SAFE) == []


def test_no_test_holds_a_tcp_port_bound_without_listening() -> None:
    files = sorted(_TESTS.glob("*.py"))
    findings = [finding for path in files for finding in unsafe_binds(path.read_text(encoding="utf-8"), path.name)]

    # The walk must have reached the files that bind sockets, or a pass means nothing.
    assert {"fake_lpd_server.py", "test_adapter_raw.py", "test_adapter_telnet.py"} <= {path.name for path in files}
    assert findings == [], (
        "TCP socket bound but never listened on while in use (macOS answers it with no reset, so the "
        f"connect times out): {findings}. Use fake_lpd_server.closed_port() for a refusing port."
    )
