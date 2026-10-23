# skill-writer checklist - sercomm-printserver (2026-10-23, first version)

- [x] Type: reference/technique skill for a CLI and library. Test approach: retrieval and
      application questions a script author meets, answered with a direct quote or NOT STATED.
- [x] Receipt held (skill_receipt.py start meta-skill-writer, this session).
- [x] RED (opus and haiku, the CLI's full `--help` output as the only material): exit codes for
      no answer / missing `--yes` / no admin rights, the JSON fields, the queue for the serial
      port, how a set password reaches later commands and whether it protects the device, and
      whether `device-config set IP_ADDR=...` waits: NOT STATED on both tiers. Both guessed the
      RAW risk; haiku guessed the address after an IP change and polled for it.
- [x] Contamination noted: this project's memory index holds the fact that probing a RAW print
      port sends a print job, so the RAW question (Q6) cannot fail honestly in a behavioural arm.
      The skill FILE carries the rule itself ("Never open a RAW port without sending a job"),
      which is the evidence for that row.
- [x] GREEN (opus and haiku, only the skill text): all eight questions answered with the
      governing quote on both tiers.
- [x] REFACTOR, three rounds (opus + haiku each, 6 cells), each closing the gaps the previous
      round reported and re-asking those questions on the final text:
      - which commands need `--yes`, which also `--confirm-name`, and that reading and printing
        need neither; `password clear` and `store-ip` rows added to the table;
      - telling the two causes of exit 77 apart by the envelope's `error`;
      - the failure envelope's fields and what `skipped` means;
      - `[device] host` is not rewritten after an IP change, pass `reachable_at` as `--host`;
      - `arp assign-ip` waits and reports `data.write.reachable_at`, an answering `--ip` exits 22,
        `--mac` in any common spelling (this exposed a code defect: a dashed MAC was refused by
        the name check; fixed with `normalise_mac` and tests for every spelling);
      - the queue-to-port keys `L1_PROUT`..`L8_PROUT`; the 0.1 s refusal after a session is
        retried by the tool itself;
      - `status` vocabulary (`Idle`/`Printing`, `Offline`).
- [x] Declined, with reason: what a job does with no printer attached (not measured yet; the skill
      says so; measured once a printer is connected); whether SETIP restarts the device (not
      measured; the skill says so); the retry budget and per-command `data` shapes (`--json` on
      the command shows them; the skill keeps to what `--help` cannot say); one-port models' queue
      mapping (the skill sends the reader to `L*_PROUT` instead of a table that would vary).
- [x] Every behavioural claim checked against the code: exit-code mapping in
      `adapters/cli/commands/_device.py`, `--yes` refusals, `ChangeReport.reachable_at`, the FTP
      client's refused-connect retry, `PrintServer.print_raw`'s empty-data refusal, `PortState`.
- [x] Description measured: 492 characters. ASCII only. Addresses are documentation values
      (192.0.2.0/24) and the project's placeholder SerComm MAC.
