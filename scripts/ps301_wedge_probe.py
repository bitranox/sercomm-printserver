"""Reproduce the PS301 RAW wedge, with and without the drain wait, and log every trial.

A PS301 takes a RAW job at once and passes it on at the printer link's speed; a NEW RAW
connection opened before that is finished loses its data and wedges the port until a restart.
This probe measures it on a real device. Each trial:

1. ``check`` must read the routed port idle (otherwise the run stops: nothing is sent into a
   busy or wedged port);
2. the job is sent to the logical printer's RAW port, by arm: ``wait`` keeps the connection open
   for the drain (what ``print raw`` does), ``close`` closes at once (the liveness control);
3. the query is sent at once on a NEW connection, and its answer read;
4. ``check`` runs at +1, +5 and +15 s;
5. the trial counts as wedged when the query got no answer or the port reads wedged at +15 s,
   and a wedged device is restarted before the next trial.

Arms alternate within each round (wait, close, wait, close, ...), so the two share the clock.
Every trial is appended to the log as one JSON line, and the run ends with a summary line.

The job PRINTS on every trial, so the run refuses to start without ``--confirm-print``. The query
must be bytes the printer answers (a status request in its own language) and that print
nothing; nothing here knows any printer language.

Pre-registered reading, per branch (the 2026-11-10 measurement on FW 6022, 9600 8N1):
* ``close`` wedges in at least 2 of 3 trials and ``wait`` in none: the drain wait held.
* ``close`` wedges in fewer than 2 of 3: the liveness control failed; the run says nothing
  about the wait (a job the printer answers after, or one too short to outlast the query, does
  this).
* ``wait`` wedges at all: the wait is too short at this size and link.

Example:
    .venv/bin/python scripts/ps301_wedge_probe.py --host 192.0.2.52 --printer 3 \\
        --job label.dpl --query status.bin --log wedge.jsonl --rounds 3 --confirm-print
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final, Literal, NamedTuple

from pydantic import AwareDatetime, BaseModel, Field

from sercomm_printserver.adapters.raw import RawPrinter, connect_retrying_refusals
from sercomm_printserver.composition import build_production
from sercomm_printserver.domain.endpoint import DeviceEndpoint
from sercomm_printserver.domain.link import link_drain_for
from sercomm_printserver.domain.port_health import PortVerdict

if TYPE_CHECKING:
    import socket
    from collections.abc import Callable, Iterator, Sequence

    from sercomm_printserver.application.ports import RawPort
    from sercomm_printserver.application.print_server import PrintServer
    from sercomm_printserver.domain.config_types import PortId
    from sercomm_printserver.domain.link import LinkDrain

#: When ``check`` reads the port after the query, in seconds after the query was sent.
CHECK_MARKS: Final = (1.0, 5.0, 15.0)
_DESCRIPTION: Final = "Reproduce the PS301 RAW wedge, with and without the drain wait, and log every trial."
#: Once an answer has started, this much silence ends it.
_ANSWER_IDLE_SECONDS: Final = 1.0
_RECV_SIZE: Final = 4096
#: The share of ``close`` trials that must wedge for the run to say anything about ``wait``.
_LIVENESS_SHARE: Final = 2 / 3


class Arm(str, Enum):
    """How the job's connection ends."""

    WAIT = "wait"
    CLOSE = "close"


class Reading(str, Enum):
    """What a run says about the drain wait, per the pre-registered branches."""

    WAIT_HELD = "the drain wait held"
    LIVENESS_FAILED = "the liveness control failed: the run says nothing about the drain wait"
    WAIT_TOO_SHORT = "the drain wait is too short at this job size and link"


class RecordKind(str, Enum):
    """Which record a log line carries."""

    TRIAL = "trial"
    SUMMARY = "summary"


class ProbeAbortedError(RuntimeError):
    """A trial could not start or finish safely, so the run stops."""


class Slot(NamedTuple):
    """One scheduled trial: its round and its arm."""

    round: int
    arm: Arm


class Check(BaseModel, frozen=True, extra="forbid"):
    """What ``check`` read for the routed port this long after the query was sent."""

    after_seconds: float
    verdict: PortVerdict


class Trial(BaseModel, frozen=True, extra="forbid"):
    """One trial, as logged."""

    kind: Literal[RecordKind.TRIAL] = RecordKind.TRIAL
    round: int
    arm: Arm
    job_bytes: int
    drain_seconds: float
    answer: str
    answered: bool
    checks: tuple[Check, ...]
    wedged: bool
    restarted: bool


class Summary(BaseModel, frozen=True, extra="forbid"):
    """How many trials of each arm wedged, and what the run therefore says."""

    kind: Literal[RecordKind.SUMMARY] = RecordKind.SUMMARY
    trials: dict[Arm, int]
    wedged: dict[Arm, int]
    reading: Reading


class LogLine(BaseModel, frozen=True, extra="forbid"):
    """One line of the JSONL log: when it was written and the record it carries."""

    t: AwareDatetime
    record: Annotated[Trial | Summary, Field(discriminator="kind")]


@dataclass(frozen=True, slots=True)
class Target:
    """What one run sends where."""

    endpoint: DeviceEndpoint
    printer: int
    raw_port: int
    routed: PortId
    drain: LinkDrain | None
    job: bytes
    query: bytes
    answer_wait: float


@dataclass(frozen=True, slots=True)
class Options:
    """What the command line asked for, typed."""

    host: str
    printer: int
    job: Path
    query: Path
    log: Path
    rounds: int
    answer_wait: float
    timeout: float
    raw_port_base: int


@dataclass(frozen=True, slots=True)
class Tools:
    """The device, the wire and the clock a run uses; replaced by fakes in tests."""

    server: PrintServer
    raw: RawPort
    query: Callable[[DeviceEndpoint, int, bytes, float], bytes]
    sleep: Callable[[float], None]
    clock: Callable[[], float]


def schedule(rounds: int) -> Iterator[Slot]:
    """The trials in order: within each round ``wait`` then ``close``.

    Example:
        >>> [(slot.round, slot.arm.value) for slot in schedule(2)]
        [(1, 'wait'), (1, 'close'), (2, 'wait'), (2, 'close')]
    """
    for number in range(1, rounds + 1):
        for arm in (Arm.WAIT, Arm.CLOSE):
            yield Slot(round=number, arm=arm)


def run_trial(target: Target, tools: Tools, *, number: int, arm: Arm) -> Trial:
    """Run one trial; a wedged device is restarted before this returns.

    Raises:
        ProbeAbortedError: The routed port was not idle before the trial.
    """
    before = _verdict(tools.server, target.routed)
    if before is not PortVerdict.IDLE:
        raise ProbeAbortedError(f"{target.routed.value} reads {before.value} before the trial; nothing was sent")
    drain = target.drain if arm is Arm.WAIT else None
    tools.raw.send(target.endpoint, target.raw_port, target.job, drain=drain)
    sent_at = tools.clock()
    answer = tools.query(target.endpoint, target.raw_port, target.query, target.answer_wait)
    checks = _checks(tools, target.routed, since=sent_at)
    wedged = not answer or checks[-1].verdict is PortVerdict.WEDGED
    if wedged:
        tools.server.reset(wait=True)
    return Trial(
        round=number,
        arm=arm,
        job_bytes=len(target.job),
        drain_seconds=0.0 if drain is None else round(drain.seconds_for(len(target.job)), 3),
        answer=answer.hex(),
        answered=bool(answer),
        checks=checks,
        wedged=wedged,
        restarted=wedged,
    )


def _checks(tools: Tools, routed: PortId, *, since: float) -> tuple[Check, ...]:
    checks: list[Check] = []
    for mark in CHECK_MARKS:
        left = since + mark - tools.clock()
        if left > 0:
            tools.sleep(left)
        checks.append(Check(after_seconds=mark, verdict=_verdict(tools.server, routed)))
    return tuple(checks)


def _verdict(server: PrintServer, routed: PortId) -> PortVerdict:
    for health in server.check().ports:
        if health.status.port is routed:
            return health.verdict
    raise ProbeAbortedError(f"the status does not list {routed.value}")


def summarise(trials: Sequence[Trial]) -> Summary:
    """Count the trials per arm and apply the pre-registered reading.

    Example:
        >>> base = dict(job_bytes=1, drain_seconds=0.0, answer="", answered=False, checks=(), restarted=False)
        >>> closed = Trial(round=1, arm=Arm.CLOSE, wedged=True, **base)
        >>> waited = Trial(round=1, arm=Arm.WAIT, wedged=False, **base)
        >>> summarise([closed, waited]).reading is Reading.WAIT_HELD
        True
    """
    counts = {arm: sum(1 for trial in trials if trial.arm is arm) for arm in Arm}
    wedged = {arm: sum(1 for trial in trials if trial.arm is arm and trial.wedged) for arm in Arm}
    return Summary(trials=counts, wedged=wedged, reading=_reading(counts, wedged))


def _reading(counts: dict[Arm, int], wedged: dict[Arm, int]) -> Reading:
    if not counts[Arm.CLOSE] or wedged[Arm.CLOSE] < _LIVENESS_SHARE * counts[Arm.CLOSE]:
        return Reading.LIVENESS_FAILED
    if wedged[Arm.WAIT]:
        return Reading.WAIT_TOO_SHORT
    return Reading.WAIT_HELD


def query_answer(endpoint: DeviceEndpoint, port: int, query: bytes, wait: float) -> bytes:
    """Send ``query`` on a new connection and return what came back within ``wait`` seconds.

    An answer ends after a second of silence once it has started; an empty result means the
    printer did not answer. The port refuses for a moment after any close, so a refused connect
    is retried as ``print raw`` retries it; one refused for the whole retry window raises.
    """
    with connect_retrying_refusals(endpoint.host, port, endpoint.timeout) as sock:
        sock.sendall(query)
        return _read_answer(sock, wait)


def _read_answer(sock: socket.socket, wait: float) -> bytes:
    received = bytearray()
    sock.settimeout(wait)
    try:
        while chunk := sock.recv(_RECV_SIZE):
            received += chunk
            sock.settimeout(_ANSWER_IDLE_SECONDS)
    except TimeoutError:
        pass
    return bytes(received)


def _parse(argv: Sequence[str] | None) -> Options:
    parser = argparse.ArgumentParser(description=_DESCRIPTION)
    parser.add_argument("--host", required=True, help="Print server address.")
    parser.add_argument("--printer", type=int, choices=(1, 2, 3), required=True, help="Logical printer L1..L3.")
    parser.add_argument("--job", type=Path, required=True, help="File with the job; it PRINTS on every trial.")
    parser.add_argument("--query", type=Path, required=True, help="File with bytes the printer answers.")
    parser.add_argument("--log", type=Path, required=True, help="JSONL file each trial is appended to.")
    parser.add_argument("--rounds", type=int, default=3, help="Rounds of one wait and one close trial each.")
    parser.add_argument("--answer-wait", type=float, default=10.0, help="Seconds to wait for the query's answer.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Network timeout per operation, seconds.")
    parser.add_argument("--raw-port-base", type=int, default=9100, help="RAW port of L1.")
    parser.add_argument("--confirm-print", action="store_true", help="Confirm that every trial prints the job.")
    args = parser.parse_args(argv)
    if not args.confirm_print:
        parser.error("every trial prints the job; pass --confirm-print to run")
    if args.rounds < 1:
        parser.error("--rounds must be at least 1")
    return Options(
        host=str(args.host),
        printer=int(args.printer),
        job=Path(args.job),
        query=Path(args.query),
        log=Path(args.log),
        rounds=int(args.rounds),
        answer_wait=float(args.answer_wait),
        timeout=float(args.timeout),
        raw_port_base=int(args.raw_port_base),
    )


def _target(args: Options, server: PrintServer) -> Target:
    config = server.read_config()
    routed = config.logical_printers[args.printer - 1].port
    job, query = args.job.read_bytes(), args.query.read_bytes()
    if not job or not query:
        raise ProbeAbortedError("the job and the query must not be empty")
    return Target(
        endpoint=server.endpoint,
        printer=args.printer,
        raw_port=args.raw_port_base + args.printer - 1,
        routed=routed,
        drain=link_drain_for(config, routed),
        job=job,
        query=query,
        answer_wait=args.answer_wait,
    )


def _append(log: Path, record: Trial | Summary) -> None:
    line = LogLine(t=datetime.now().astimezone(), record=record).model_dump_json() + "\n"
    with log.open("a", encoding="utf-8") as handle:
        handle.write(line)
    sys.stdout.write(line)
    sys.stdout.flush()


def run(args: Options, tools: Tools, target: Target) -> Summary:
    """Run every scheduled trial, logging each one, and log the summary."""
    trials: list[Trial] = []
    for slot in schedule(args.rounds):
        trial = run_trial(target, tools, number=slot.round, arm=slot.arm)
        trials.append(trial)
        _append(args.log, trial)
    summary = summarise(trials)
    _append(args.log, summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the arguments, run the probe, exit 0 on a completed run and 1 on an aborted one."""
    args = _parse(argv)
    endpoint = DeviceEndpoint(host=args.host, timeout=args.timeout)
    server = build_production().open_print_server(endpoint, raw_port_base=args.raw_port_base)
    tools = Tools(server=server, raw=RawPrinter(), query=query_answer, sleep=time.sleep, clock=time.monotonic)
    try:
        run(args, tools, _target(args, server))
    except ProbeAbortedError as error:
        sys.stderr.write(f"probe stopped: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
