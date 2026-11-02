# skill-writer checklist - sercomm-printserver (2026-11-02, `print raw --verify`)

- [x] Type: reference skill for a CLI and library. Test approach: a script-author scenario (a
      nightly `print raw` whose job blocked the port and reported success), each claim answered
      with a direct quote or NONE, plus a `Skill gaps` section in every reply.
- [x] Receipt held (skill_receipt.py start meta-skill-writer).
- [x] Context check: the lesson is new behaviour of this change, so no CLAUDE.md or memory text
      teaches it; the probes read only the pasted text, and their quotes were checked against it.
- [x] RED (opus, pre-edit text, 1 cell): hand-written `status` polling with a guessed output
      format, a guessed 300 s limit and invented exit codes 3 and 4; "No exit code reports a blocked
      port" answered NONE.
- [x] GREEN (opus and haiku, edited text, 4 questions, 2 cells): both tiers wrote
      `print raw 3 label.dpl --host H --verify`, branched on 110 and raised `--verify-timeout` for
      the long job, with the governing quote. Gaps closed in REFACTOR: exit 69 could mean sent or
      unsent, so a script could not decide on a resend (fixed in the code: every failure after the
      send is `JobNotDrainedError`, exit 110); the exit code cannot tell this job from an earlier
      one (now stated).
- [x] REFACTOR re-probe (opus and haiku, final wording, 4 questions, 2 cells): the governing quote
      on all four on both tiers. Gap closed afterwards: whether the clock starts at the start or the
      end of the send (now "after the send finished", as `_wait_for_idle` takes its deadline after
      `raw.send` returns).
- [x] Every command the change adds was executed against the real device: `--verify` with a printer
      exits 0 with `idle_port`; with no printer on the routed port, exit 110 and
      `JobNotDrainedError`; `reset --yes` then reads every port `Idle`.
- [x] Mechanism claims checked against the code: `print_raw_verified` and `_wait_for_idle`
      (`application/print_server.py`), `JobNotDrainedError` maps to exit 110
      (`adapters/cli/commands/_device.py`), the usage error (`adapters/cli/commands/printing.py`).
- [x] Gaps declined, with reasons:
      - what `reset --yes` does to another port's job or to this job's unprinted data: not measured;
        the skill states only what was measured.
      - how to confirm a page printed: the device offers no such signal; the skill says what success
        does and does not mean.
      - how to estimate a job's duration: depends on the printer and the job; judgement left open.
      - the JSON flag, the usage-error exit code, what `3` means, `--host` on `reset`: stated
        elsewhere in SKILL.md ("Output and exit codes", "Ports, queues and printers", the paragraph
        under "Pick the command"); the probes saw an excerpt.
- [x] Width and fence check over the added lines: only the exit-code table row exceeds 100 columns,
      and the formatter re-padded that table.
- [x] No version-history wording added; no non-ASCII added; example addresses are reserved values.
- [x] Not mirrored in bitranox-skills (`repo-gate.py --mirrors` lists no sercomm pair).

## Waiting for a busy port before the send (same day)

This section replaces the "message says the port was busy before this job" wording above: the
command now waits, and a port still busy before the send exits 75 with nothing sent.

- [x] RED (text check on the pre-edit paragraph): it said a busy port still gets the job and left a
      script no safe way to tell a resend is allowed. No behavioural RED: the installed text teaches
      behaviour this change removes.
- [x] Executed against the real device: a port held by a first job, then `--verify --verify-timeout
      3` exits 75 with `PortBusyError`; the `--verify` runs with a printer (exit 0) and with no
      printer (exit 110) still behave as above; `reset --yes` clears the port.
- [x] GREEN (opus and haiku, 5 questions, 2 cells): the governing quote on all five on both tiers.
- [x] Gaps closed after GREEN: 110 can be a healthy job outlasting the timeout, so read `status`
      before a reset; a port taken just before the send was worded as a contradiction of "the data
      was sent"; exit 69 said nothing about whether data went out (the mechanism is in
      `adapters/raw/printer.py`: a refused connect sends nothing, and a failure in the send loop
      comes after earlier pieces went out).
- [x] Gaps declined, with reasons:
      - what happens to stacked jobs on a port with a working printer, and what a reset does to a
        job or to other ports: not measured; the skill states only what was measured.
      - separate codes for the causes of 110: all mean "sent, port not confirmed free"; `status`
        tells them apart.
      - the margin above a job's duration, and estimating it: judgement left open.
      - the JSON flag, the meaning of `3`: stated elsewhere in SKILL.md; the probes saw an excerpt.
