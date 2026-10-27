# skill-writer checklist - sercomm-printserver (2026-10-27, revision)

- [x] Type: reference skill for a CLI and library. Test approach: retrieval and application
      questions a script author meets, answered with a direct quote or NONE, plus a `Skill gaps`
      section in every reply.
- [x] Receipt held (skill_receipt.py start meta-skill-writer).
- [x] Order: the edit was written before the baseline ran. The pre-edit text is unchanged in git
      (`git show HEAD:skills/sercomm-printserver/SKILL.md`), so the RED arms ran on that text,
      pasted in full, and the GREEN arms on the edited text. A probe given the pre-edit text
      cannot have seen the edit.
- [x] RED (opus and haiku, pre-edit text only, 12 questions, 2 cells): NONE or a guess on 9-11
      of 12 on both tiers: cooldown install, telling a factory reset from the address, the
      CAP_NET_RAW cause of exit 13, store-ip and an unapplied IP_ADDR, the mail password after an
      export and import, the read-back exit 76, a usage error under `--json-bare` (both tiers
      read the table as 22 and saw the `print raw 4` exit 2 as a contradiction), LPD to a port
      without a printer, the SNMP-silent outcome, the `write_config` call, the TEW-P1U1P layout.
      Both tiers answered "`arp factory-reset` waits" from "`arp` always waits", which was wrong.
- [x] Contamination: the opus RED cited two commit titles from the session's injected git
      context for Q5 and Q6 instead of the pasted text, so those two RED cells are void on
      opus; haiku answered them NONE from the text.
- [x] GREEN (opus and haiku, edited text, same 12 questions, 2 cells): 10 of 12 answered with the
      governing quote on both tiers. Gaps reported and closed in REFACTOR: no assembled cooldown
      command; LPD timeout as exit 76 not in the exit table; no model-to-port layout; whether
      `--ip OLD_IP` passes the free check when the device itself holds it; how to wait after a
      factory reset; whether the library needs a confirmation; what `reachable_at` holds.
- [x] REFACTOR re-probe (haiku, the five touched questions on the final sections): all five
      answered by quote. A second quote-back (haiku) on the last two fixes (poll limit,
      `confirm_name=` required) answered both by quote.
- [x] Declined, with reason: a poll interval and what a script does after giving up (the
      script's own judgement); the `confirm_name` type and the full signatures (`help()`
      answers them); a restore path without an export taken before the reset (none exists, and
      the text says to export first); which queue count belongs to each model (the text sends
      the reader to `L*_PROUT` on the device instead of a table that firmware varies);
      capabilities granted but not in effect for the process (generic Linux, not this tool);
      the SNMP community being configurable (not measured).
- [x] GREEN diffed against RED in both directions: no RED answer that was right is lost; the two
      RED answers that were wrong (factory-reset waits, usage error 22) are now answered
      correctly.
- [x] Every behavioural claim checked against code or measurement: exit mapping
      (`adapters/cli/commands/_device.py`), the free-address check accepting the device's own
      MAC (`application/arp_trick.py`), `ConfigFormatError` for missing `DHCP_MODE` (exit 22),
      the LPD acknowledgement timeout raising `DeviceResponseError`, `ConfigWriteResult` fields
      and `reachable_at` semantics, `with_value` refusing an unknown key and a bad value (run),
      the Python example (run), the cooldown install command (run, rc 0), factory-reset device
      facts (device E2E, FW 6022), the model ports (firmware images, `docs/config-keys.md`).
- [x] History finder over the skill directory: no hits. Addresses are documentation values
      (192.0.2.0/24) and the project's placeholder SerComm MAC.
- [x] Description measured: 609 characters. ASCII only.
