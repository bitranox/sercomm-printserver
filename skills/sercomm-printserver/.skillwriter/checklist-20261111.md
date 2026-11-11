# skill-writer checklist - sercomm-printserver (2026-11-11, `check` and the serial drain wait)

- [x] Type: reference skill for a CLI and library. Test approach: a script-author scenario (a
      nightly `print raw 3` to a serial printer exits 110 with SP reading "Printing / Direct
      Socket", 0 bytes serviced), each claim answered with a direct quote or NONE, plus a
      `Skill gaps` section in every reply.
- [x] Receipt held (skill_receipt.py start meta-skill-writer); decision ledger read
      (`skill_decisions.py show`, no entries for this skill).
- [x] Context check: the lesson is new behaviour of this change (the `check` command, exit 3, the
      drain wait), so no CLAUDE.md or memory text teaches it; the probes read only the pasted
      text, and their quotes were checked against it.
- [x] RED (text check on the pre-edit SKILL.md, `git show HEAD:`): 0 hits for `wedge`, `baud` and
      an exit-3 row; after exit 110 the only advice was "read `status` before `reset --yes`",
      which cannot tell a wedged port from one a client holds, and the probe rule forbade any
      "port probe" without telling a bare connect from one that sends data. No behavioural RED:
      the installed text predates the feature.
- [x] Executed against the real device (FW 6022, all ports idle): `check --host H` exits 0 with
      the table (every port `idle`, nothing probed); `check --json-bare` exits 0 with `ok` true and
      `data.ports[].verdict`, `data.wedged` false, `data.restarted` false; `check --reset` without
      `--yes` exits 77 with "check --reset restarts the device when a port is wedged; pass
      --yes". The wedged and held paths are covered by the CLI and use-case tests against the
      in-memory device (`tests/test_cli_device.py`, `tests/test_print_server.py`); a real wedge
      needs a print run, which is not done here.
- [x] Mechanism claims checked against the code: the verdicts and `unprobed` meaning
      (`domain/port_health.py` `unprobed_verdict`, `is_wedge_candidate`); probing only candidates
      and only the RAW ports routed there (`application/print_server.py` `_judge`,
      `_raw_ports_routed_to`); the exit-3 envelope is the success shape with `ok` false
      (`adapters/cli/commands/_device.py`, `outcome` hook); the drain is computed from CONFIG
      (`domain/link.py` `link_drain_for`, `print_server._send_raw`).
- [x] GREEN (opus and haiku, 6 questions, 2 cells): both tiers named `check --host H` to tell
      wedged from held and `check --reset --yes` to restart only on a wedge, exit 3, the
      unprotected foreign program, the serial wait, `unprobed`, and the bare-connect rule, each
      with the governing quote.
- [x] Gaps closed after GREEN: the exit-3 JSON shape (now "the success shape ... with `ok`
      false"); whether a job sent into a wedged port must be resent (now stated); what `data`
      holds (per-port `status` and `verdict`, `wedged`, `restarted`); "that state" now spelled
      out; every `print raw` reads CONFIG, not only serial ones; the drain uses the configured
      baud rate; `check --reset` added to the list of commands that exit 77 without `--yes`.
- [x] REFACTOR re-probe (opus and haiku, 5 questions, 2 cells): resend after a cleared wedge, the
      `data` fields, which reading `check` probes, CONFIG read for a parallel `print raw`, the
      exit-3 JSON shape; the governing quote on all five on both tiers. Gaps closed afterwards:
      "do not resend it blindly" (exit 110) pulled against "must be sent again" (now: a job a
      plain `print raw` sent into an already wedged port never printed; after a 110 naming a wedge
      the device cannot say whether this job printed, so look at the output first); the type of
      `wedged` and `restarted` (booleans).
- [x] Final re-probe on the final text (opus and haiku, 4 questions, 2 cells): 110 with a wedge
      then a cleared wedge (look at the output, no automatic resend), 75 then a cleared wedge
      (send), a plain send into an already wedged port (did not print), the type of `restarted`;
      the governing quote on all four on both tiers, no new undecided gap.
- [x] Gaps declined, with reasons:
      - how to judge from the printer's output whether a job printed: depends on the job and
        the printer; the device gives no signal, which the text states.
      - whether a 75 message names a wedge too: a script branches on the exit code, never on the
        message text ("Output and exit codes").
      - whether `check --reset --yes` exits 3 when the restart did not clear the wedge, and what
        exit 0 means when nothing was wedged: the exit-code row and "Exit 3 means a port is
        wedged, 0 that none is" state both; the final probes saw an excerpt without that row.
      - whether a bare connect during an in-flight serial job can wedge the port: not measured;
        `check` probes only a port already reading the wedge pattern, which the text states.
      - a command to read the routing: covered in "Ports, queues and printers"
        (`device-config get L3_PROUT`); the probes saw an excerpt.
      - flow control or a printer slower than the baud rate: not measured; the text calls the
        wait a computation from the configured rate.
      - the `sercomm-printserver` prefix on bare subcommands: the whole skill uses bare
        subcommands under its "Pick the command" convention.
- [x] Width and fence check over the added lines (scratch widthcheck over `git diff -U0`): 0
      findings; the exit-code table was re-padded by the formatter.
- [x] No version-history wording added; no non-ASCII added; example addresses are reserved values.
- [x] Not mirrored in bitranox-skills (`repo-gate.py --mirrors` lists no sercomm pair).
- Decisions: none - the skill keeps no decision ledger and this change records no rule a later
  editor could undo without a measurement; the design decisions live in
  `docs/plans/2026-11-11-ps301-wedge-design.md`.
