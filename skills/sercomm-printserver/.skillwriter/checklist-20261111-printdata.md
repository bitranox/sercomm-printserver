# skill-writer checklist - sercomm-printserver (2026-11-11, streaming print data and the Unreleased changes)

- [x] Type: reference skill for a CLI and library. Test approach: a text check of the file for each
      `## [Unreleased]` CHANGELOG item, then a script-author retrieval probe (7 questions), each
      answer with a direct quote or NONE, plus a `Skill gaps` section.
- [x] Decision ledger read (`skill_decisions.py show sercomm-printserver --skill-dir
      skills/sercomm-printserver`, with and without `--kind rejected,removed --full`): no entries.
- [x] Context check: the lesson is new behaviour of unreleased code (exit 65 and 74, `PrintData`),
      so no CLAUDE.md or memory text teaches it; the probes read only the pasted text and their
      quotes were checked against it.
- [x] RED (text check on `git show HEAD:skills/sercomm-printserver/SKILL.md`): 0 hits for an exit-65
      row, an exit-74 row, `PrintSourceChangedError`, `SpoolError`, `PrintData.from_path`,
      `PrintData.from_stream`, the 64 KiB import limit, the first-line rule of `--from-file`,
      `occupant`, `data.size`, `TMPDIR`, the `check` fields `probed` and `before`, and the
      separate `discover --timeout`; the Python example read the job with `open(...).read()`.
      The frontmatter did not parse as YAML (`Ready.": finding` puts `: ` in the plain scalar).
- [x] Executed, not reviewed:
      - every command and flag the skill names against `--help` of the worktree build
        (`discover --timeout` is 0.1-60, default 3; every other `--timeout` 0.1-600);
      - every exit code against `adapters/cli/exit_codes.py` and `exit_code_for`
        (`SpoolError` 74, `PrintSourceChangedError` 65, `ConfigFormatError` 22);
      - both Python snippets against `FakeDevice` (in place of `open_print_server`, whose
        signature was inspected): `print_lpd` with `PrintData.from_path` returned 5 bytes,
        `print_raw` with `PrintData.from_stream(sys.stdin.buffer)` sent the stdin bytes, a second
        read of one stream raises `RuntimeError`, a rewound stream wraps again, `len(PrintData)`
        raises `TypeError`, `print_raw_verified` defaults `timeout=30` and returns `PortStatus`,
        `occupant` gives `Occupant.DIRECT_SOCKET` / None with `occupied_by` kept, `CheckResult`
        fields are `ports`, `restarted`, `before`, `wedged`; a spool that cannot be created raises
        `SpoolError` before the LPD connection opens;
      - `device-config import` of a file one byte over 64 KiB through the CLI with the fake device:
        exit 22 `ConfigFormatError` with and without `--yes`, no file read from or action sent to
        the device;
      - the install lines: `uvx sercomm-printserver --version` and the documented cooldown form
        both resolve 0.3.0 (rc 0); a control without the exemptions also resolves today, because
        0.3.0 is older than 7 days. The next release will be younger than the window: its own
        dependency floors (this worktree's pyproject) resolve under `--exclude-newer "7 days"`
        with and without the library exemptions, so the documented form, which exempts
        `sercomm-printserver` itself, still resolves; the install mechanics are unchanged.
- [x] Mechanism claims checked against the code: spool before connect and the empty-job refusal
      (`adapters/lpd/client.py` `LpdClient.submit`), the size mismatch handling (`_send_content`),
      the import limit (`device_config.py` `CONFIG_FILE_LIMIT`, `_read_config_file` called before
      `_write`), the first-line password (`device.py` `_new_password`), RAW retry 3 s and drain
      margin 0.25 s (`raw/printer.py`, `domain/link.py`).
- [x] GREEN (opus and haiku, 7 questions, 2 cells): both tiers answered all seven from the governing
      quote: exit 65 (part may be on paper, look first, print a finished file), exit 74 (nothing
      sent, make room in `TMPDIR`), the streaming Python with `PrintData.from_path`, the 64 KiB
      import refusal with 22, line 1 of the password file, `occupant`, and `discover --timeout`.
- [x] Gaps closed after GREEN: whether the oversized import is refused before the device is
      contacted and also without `--yes` (now in the 22 row, measured above); what `occupied_by`
      holds for a free port (None, now stated); how to send a stream twice (rewind or reopen, then
      a new `PrintData`); the `discover --timeout` sentence now says outright that it leaves
      `[device] timeout` alone.
- [x] Gaps declined, with reasons:
      - an automated next step after exit 65: the device gives no signal whether the part printed,
        which the text states; judging the paper is the operator's.
      - whether an unterminated LPD job leaves the queue occupied: not measured.
      - that a consumed pipe must be produced again, and how much room the spool needs: the text
        says the data is copied to a file, so both follow.
      - `PrintJob.name` optional, closing the server, trailing whitespace in the password file,
        discover parallelism: `--help` and `help()` answer these; the page gives what they cannot.
      - "device command" covering `discover` once and not once, "all eight", `config-deploy` not in
        the table: the probes saw an excerpt without the queue section; `config-deploy` is a
        template command documented by `--help`.
- [x] Width and fence check over the added lines: 0 findings outside the frontmatter description;
      the frontmatter now parses with `yaml.safe_load` (`['description', 'name']`, description
      610 characters); no history wording (finder over the file); no non-ASCII; addresses are
      192.0.2.x; example paths are /tmp and /opt.
- [x] Not mirrored in bitranox-skills (no sercomm pair, as recorded in checklist-20261111.md).
- Decisions: none - the skill keeps no decision ledger and this change records the code's current
  behaviour, no choice a later editor could undo without a measurement.
