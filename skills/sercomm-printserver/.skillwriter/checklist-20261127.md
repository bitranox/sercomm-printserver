# skill-writer checklist - sercomm-printserver (2026-11-27, RAW ports in two rows by firmware)

- [x] Type: reference skill for a CLI and library. Test approach: a retrieval scenario (a 6A10
      device, a RAW job to `L3`), each claim answered with a direct quote or NOT STATED, plus a
      `Skill gaps` section in every reply.
- [x] Receipt held (skill_receipt.py start meta-skill-writer). No decision ledger exists for this
      skill (`skill_decisions.py show` printed nothing).
- [x] Ground truth before the edit:
      - Measured by a peer session on a PS301 with firmware 6A10 (2026-11-27): 9100-9102 refused
        every connect for over 8 min after a restart; 4010, 4020, 4030 and 515 accepted. On a
        PS301 with firmware 6022 both rows accept (earlier skill text, measured).
      - The code after this change: `print raw N --row base|dsi` (`printing.py`, shown in
        `print raw --help`), `raw_port_of` maps printer 1/2/3 to 4010/4020/4030 in the DSI row,
        `raw_port_rows("6A10")` is the DSI row only, and `PrintServer._probe_row` makes `check`
        probe the DSI row there. `firmware --host H` exists (`device.py`, `cli_firmware`);
        `device info` does not (`No such command 'device'`), only `device-info`.
      - Mutation: `_probe_row` forced to BASE KILLED both 6A10 check tests
        (`assert [9102] == [4030]`, mutation_arm.py).
- [x] RED (opus and haiku, pre-edit text, 1 scenario, 2 cells): both answered `print raw 3` and
      port 9102, and whether it accepts on 6A10 as NOT STATED; opus also read the DSI sockets as
      scoped to 6022 only.
- [x] GREEN (opus and haiku, edited text, 2 cells): both answered `print raw 3 --row dsi` and port
      4030 with the governing quote, and named the base-row refusal on 6A10.
- [x] Gaps closed after GREEN: the printer-to-DSI-port order (now "printer 1, 2, 3 in that
      order"), that 4010-4030 were MEASURED as accepted on 6A10, the command that prints the
      firmware (`device info` was wrong; now `firmware --host H`), what `check` probes on 6A10,
      and "all eight" (now "all eight logical printers").
- [x] REFACTOR re-probe (haiku, final wording, 5 questions, 1 cell): L2 on 6A10 is
      `print raw 2 --row dsi` on 4020, measured accepted, `firmware --host H`, and `print raw 2`
      on 6022 is 9101, each with its quote. It read "`check` probes the base row, and the DSI row
      on 6A10" two ways; reworded to "probes the base row; on 6A10 it probes the DSI row instead".
- [x] Gaps declined, with reasons:
      - the file and host arguments of `print raw`: stated elsewhere in SKILL.md (the quick
        reference table and `--help`); the probes saw an excerpt.
      - what `print raw` without `--row` does on 6A10: the connect is refused like any refused
        port, covered by the exit-code table elsewhere in SKILL.md.
      - other models than the PS301: not measured; the text keeps "measured on a PS301".
- [x] Width and fence check over the added lines: no finding. No non-ASCII added. No
      version-history wording added. Example addresses are placeholders (`H`).
- [x] The paragraph before and after the edit read: the `logical_printers` paragraph and the
      following section still bind to their own text.
- [x] Not mirrored in bitranox-skills (no mirror found).
- Decisions: none - the skill keeps no decision ledger and this change records the CLI's and the devices' current behaviour
