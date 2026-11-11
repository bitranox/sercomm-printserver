# PS301 RAW port wedge: drain wait, `check`, probe

Design agreed with the user on 2026-11-11 (backlog item [55]). The measurements it rests on are
in `docs/Manual-PS301.md` and in the module docstrings that cite them.

## The defect

A PS301 takes a whole RAW job at once and passes it on to a serial printer at line speed (about
960 B/s at 9600 8N1). A NEW RAW connection opened before that is finished loses its data, and
the port is left reading `Printing`, occupied by `Direct Socket`, 0 bytes serviced, with no
client. Only a restart clears it. Keeping the job's connection open until the drain is over
prevents it.

## 1. Drain wait in `print raw`

- `PrintServer.print_raw` reads the configuration (one FTP session) and finds the physical port
  the logical printer is routed to (`Ln_PROUT`). `--verify` already read it.
- Routed to `SP`: the link rate is `baud / (1 start + data bits + parity bit + stop bits)`
  bytes per second. Routed to a parallel port or USB: no wait. That a parallel port needs none is
  unmeasured.
- `RawPrinter.send` takes the rate as a `LinkDrain` (rate plus a 0.25 s margin). After the last
  byte it keeps the connection fully open until every byte the socket took has had the rate to
  reach the printer, plus the margin, and only then half-closes and waits for the device's close.
  A half-close does not protect anything: the PS301 closes 0.07 s after EOF, long before the
  printer has the data. A failed write raises at once without waiting.

## 2. `check`

- Reads the monitor. A port reading `Printing` / `Direct Socket` / 0 bytes serviced is a
  candidate; only then the configuration is read and each RAW port (L1..L3) routed there gets a
  bare connect with no data, with the usual 3 s retry of a refused connect.
- Verdicts: `idle`, `printing`, `held` (a probe was refused: another client holds the port; a
  second connect while one is open is refused outright), `wedged` (every probe was accepted),
  `unprobed` (a candidate no RAW port is routed to). Requiring every probe to be accepted errs
  towards `held`, so a live job is never reported as a wedge.
- Exit 0 when nothing is wedged, 3 when something is. `print raw --verify` uses the same
  classifier, so its busy and not-drained errors say `wedged` or `held` when they are.
- Not detected: a RAW port that refuses every connect while the monitor reads Idle, and a port
  that reads Idle while the printer does not answer. The first is reported by `print raw`'s
  refusal message already; the second needs the printer's own protocol.

## 3. `check --reset --yes`

Restarts the device only when something is wedged, waits for the restart as `reset` does, runs
the check again and exits 0 only when the wedge is gone. `--reset` without `--yes` is refused
(exit 77), like every other command that changes the device.

## 4. `scripts/ps301_wedge_probe.py`

A maintainer tool that reproduces the measurement. Arguments: host, logical printer, a job file,
a query file (bytes the printer answers), rounds. Two arms run interleaved, `wait` (the drain
wait) and `close` (no wait, the liveness control). A trial: check the port is idle, send the job,
send the query at once on a new connection and read the answer, run `check` at +1, +5 and +15 s,
restart on a wedge, append one JSON line. No address and no printer language are built in.

## Memory

Nothing grows with input: the job is the bytes the caller already holds, the check holds one
monitor read and one configuration, the probe writes each trial to its log and keeps only the
current one.

## Testing

Unit tests drive `PrintServer` through the in-memory fake device and `RawPrinter` against a local
TCP server, with an injected clock and sleep for the wait. The real-device run of the probe
prints labels on the test printer, so it runs only with the user's go.
