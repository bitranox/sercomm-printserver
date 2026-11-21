# skill-writer checklist - sercomm-printserver (2026-11-21, routes in one call, JSON flag position)

- [x] Type: reference skill for a CLI and library. Test approach: a retrieval scenario (a script
      that labels each RAW port with the physical port it feeds), each claim answered with a
      direct quote or NONE, plus a `Skill gaps` section in every reply.
- [x] Receipt held (skill_receipt.py start meta-skill-writer). No decision ledger exists for this
      skill (`skill_decisions.py show --kind rejected,removed --full` printed nothing).
- [x] Ground truth before the edit, against a PS301 (FW 6022) and the code:
      - `device-config show --host H --json-bare` exits 0; `data` holds `host`, `config`, `text`;
        `data.config.logical_printers` is a LIST of objects (`number`, `port`, `pre_string`,
        `post_string`, `convert_lf`, `name`), numbers 1..8, no `lp` entry. The list is built from
        the slots the CONFIG holds (`_logical_printers` in `domain/config_reader.py`), and `port`
        is the `PortId` enum (`P1`, `P2`, `P3`, `SP`, `domain/config_types.py`).
      - `device-config get L1_PROUT --host H --json-bare` exits 0 with the value in `data.value`.
      - `sercomm-printserver --json status ...`, `sercomm-printserver --json-bare device-config get
        ...` and `device-config --json-bare show ...` each exit 2 with "No such option" on stderr
        and nothing on stdout.
- [x] RED (haiku, pre-edit text, 2 questions, 1 cell): wrote three `device-config get` calls,
      could not name the JSON key holding the port ("the script must read one real response to
      find it"), and put `--json-bare` before the subcommand, judging it "Probably works"; the
      placement question answered NONE.
- [x] GREEN (opus and haiku, edited text, 2 questions, 2 cells): both wrote
      `sercomm-printserver device-config show --host H --json-bare`, read
      `data.config.logical_printers` with `number` and `port`, and refused the global placement
      with exit 2, each with the governing quote.
- [x] Gaps closed after GREEN: which entries the list holds on a model with fewer queues, whether
      `lp` appears, and the closed set of `port` values (now stated from the code above).
- [x] REFACTOR re-probe (haiku, final wording, 3 questions, 1 cell): the governing quote on the
      JSON path, on `lp` and on the `port` values; the count on a three-queue model was inferred
      correctly (three) from "one object per logical printer the CONFIG holds".
- [x] Gaps declined, with reasons:
      - how a TEW-P1U1P names its USB port in CONFIG: not measured on that model; `PortId` holds no
        USB value, and the skill states only the code's set.
      - whether the `show` shape is the same on other models and firmware: one parser serves all
        models; other models were not measured.
      - the program prefix, exit 0 on success, where `raw_port_base` is set, the DSI sockets:
        stated elsewhere in SKILL.md (the install block and "Run `sercomm-printserver <command>
        --help`", the exit-code table, "Ports, queues and printers"); the probes saw an excerpt.
- [x] Width and fence check over the added lines: no finding. No non-ASCII added. No
      version-history wording added. Example addresses are placeholders (`H`).
- [x] The paragraph after each insertion point read: "RAW ports belong ..." and the exit-code
      table still bind to their own text.
- [x] Not mirrored in bitranox-skills.
- Decisions: none - the skill keeps no decision ledger and this change records the CLI's current behaviour
