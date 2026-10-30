# skill-writer checklist - sercomm-printserver (2026-10-30, RAW refused-connect retry)

- [x] Type: reference skill for a CLI and library. Test approach: a script-author scenario (two
      RAW jobs back to back, later an exit 69 while `status` shows the port `Idle`), each question
      answered with a direct quote or NONE, plus a `Skill gaps` section in every reply.
- [x] Receipt held (skill_receipt.py start meta-skill-writer).
- [x] Context check: the lesson is new behaviour of this release (the RAW retry and the stuck-port
      message), so no CLAUDE.md or memory text teaches it; the probes read only the pasted skill
      file, and every quote they returned was checked against that file.
- [x] RED (opus and haiku, pre-edit text, 3 questions, 2 cells): NONE on all three on both tiers
      (does `print raw` retry a refused connect and need a pause; what clears a port refusing
      while `Idle`; does success mean printed). Both tiers read the FTP 0.1 s retry sentence as
      FTP-only and said so; haiku guessed the refusal was transient.
- [x] GREEN (opus and haiku, edited text, same 3 questions, 2 cells): the governing quote on all
      three on both tiers. Gaps reported and closed in REFACTOR: telling this exit 69 from a down
      device (the envelope's `error` is the same); a `--timeout` below the refusal window; whether
      to resend after the reset; whether the stuck state is the "Printing / Direct Socket" one.
- [x] REFACTOR re-probe (opus and haiku, final text, 5 questions, 2 cells): the governing quote on
      all five on both tiers. Both tiers then found that `--timeout 1` or a wrong `raw_port_base`
      makes the `status` test misfire; the sentence now names both conditions. Quote-back on
      haiku for that sentence: correct quote, and the right conclusion that `--timeout 1` does not
      satisfy it.
- [x] Mechanism claims checked against the code: the retry window is
      `min(timeout, _REFUSED_RETRY_SECONDS)` with `_REFUSED_RETRY_SECONDS = 3.0`
      (`adapters/raw/printer.py`); `DeviceUnavailableError` maps to exit 69
      (`adapters/cli/commands/_device.py`); `--timeout` is the top-level option, default 10 s.
- [x] Gaps declined, with reasons:
      - how long a stuck port stays stuck, and whether it clears without a reset: not measured;
        the skill states only what was measured ("for minutes").
      - what `reset --yes` does to jobs queued on other ports: not measured.
      - how to confirm a page printed: the device offers no such signal; the skill says what a
        success does and does not mean.
      - a contradiction between the two stuck states (final haiku probe): the text names them as
        different states in the same sentence; a misread, no change.
- [x] No version-history wording added (finder run over SKILL.md: no hits); no non-ASCII added.
- [x] Not mirrored in bitranox-skills (`repo-gate.py --mirror-of .`: no mirror); plugin version
      moves with the 0.2.2 bump.
