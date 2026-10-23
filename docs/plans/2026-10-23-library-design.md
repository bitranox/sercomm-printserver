# sercomm-printserver: library and CLI design

Status: accepted 2026-10-23. Device facts behind this design: `docs/Manual-PS301.md`.

## Goal

A Python library and CLI that manage and print to the SerComm print-server family: the
Sercom PS301 and its OEM twins (TRENDnet "Netprint", Perle IOPRINT+, Netgear PS10x/PS11x,
Linksys PPSX1/EPSX3), both the 1-port models and the 2 parallel + 1 serial models.

## Scope of the first release

- Manage: firmware version (FTP `SYST`), device info (`PSINF`), configuration (`CONFIG`) read,
  diff and write, port status (Telnet `monitor`), reset, factory default, password set and
  clear, store IP (`SETIP`).
- Print: send print data over LPD (queue `L<n>`) and RAW TCP, usable as a library API.
- Discover: find devices on a network.
- ARP trick from the vendor manuals: assign an IP to a device by its MAC (static ARP entry,
  ping, TFTP `get SETIP`) and factory-reset a device whose IP is unknown (static ARP entry,
  TFTP `GET DEFAULTC`).
- Every CLI command answers in human form or JSON (`--json`, `--json-bare`) with the envelope
  `{ok, command, data, skipped}`; diagnostics go to stderr; exit codes do not depend on the
  output format. A Claude Code skill shipped in this repo drives the CLI through that JSON.

Out of scope: firmware upload. No code path writes firmware.

## Decisions

| Topic               | Decision                                                                                                                                                                                                      | Reason                                                                                                                       |
|---------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------|
| CONFIG model        | Fully typed Pydantic model built from a key catalogue (line number, exact key token including padding such as `TCPIP_P :`, value type, availability per model/firmware)                                       | Validation before anything reaches the device                                                                                |
| Unknown CONFIG keys | Carried unchanged in an `unknown` field, written back at their line number, reported as a warning                                                                                                             | Every model of the family stays writable without losing settings the catalogue does not know yet (WLAN keys, other firmware) |
| Destructive actions | One named method per action, never a generic `get(name)`; CLI: config write shows a diff and needs `--yes`; reset needs `--yes`; factory default, password clear and set-ip also need `--confirm-name <name>` | `get` on `RESET`, `DEFAULTC`, `PASSRESET` or `SETIP` triggers the action; factory default sets the IP to 0.0.0.0             |
| Static ARP entry    | Set natively through `ipscout` (netlink on Linux, IP Helper on Windows, routing socket on macOS), behind a `NeighborTable` port                                                                               | No subprocess and no locale-dependent output; `ipscout` already reads the neighbour cache natively on all three platforms    |
| Discovery           | TCP connect to port 21 across the network, keep hosts answering `220 Print Server Ready.`, ask `SYST` for the firmware, take the MAC from the neighbour cache                                                 | Finds every family member regardless of its MAC vendor prefix and never touches a print port                                 |
| Protocol clients    | FTP: stdlib `ftplib` in active mode (the device answers `PASV` with `500 Invalid command`); Telnet, LPD (RFC 1179), TFTP (RFC 1350) and RAW: small own clients                                                | No dependency for a handful of commands; stdlib `telnetlib` no longer exists in Python 3.13                                  |
| API style           | Synchronous, explicit timeouts                                                                                                                                                                                | One device, one FTP connection at a time                                                                                     |
| RAW port per queue  | Parameter with a configurable map, default `9100 + n`                                                                                                                                                         | Manuals name 4010/4020/4030, the PS301 has 9100-9102 open; which applies is not yet verified                                 |
| Python floor        | 3.10                                                                                                                                                                                                          | Template floor; generic envelope written with `TypeVar`/`Generic`                                                            |
| Skill distribution  | This repo is its own Claude Code marketplace (`.claude-plugin/`, `skills/sercomm-printserver/SKILL.md`)                                                                                                       | Installable from any project                                                                                                 |

## Architecture

Clean layers as in the template (import-linter: composition -> adapters -> application ->
domain).

- `domain`: configuration model and key catalogue, parse/render/diff of `CONFIG`, `PSINF` and
  monitor parsers, enums (ports, protocols, serial settings), discovery result, errors.
  Parse and render are pure; render of an unchanged parse is byte-identical to the input.
- `application`: ports (`ManagementTransport` for FTP, `MonitorClient`, `TftpClient`,
  `LpdClient`, `RawPrinter`, `NeighborTable`, `HostScanner`) and the use cases. The public
  library facade `SercommPrintServer` is exported from the package root.
- `adapters`: one package per protocol, in-memory fakes for every port, the CLI, and the
  `[device]` configuration section (`defaultconfig.d/50-device.toml`: host, login name,
  password, timeout, RAW port map).
- `composition`: wires production and testing services.

## CLI

```
sercomm-printserver discover [--network CIDR]
sercomm-printserver info | status | firmware                [--host HOST]
sercomm-printserver config show | get KEY | set KEY=VALUE... [--yes] | export FILE | import FILE [--yes]
sercomm-printserver reset --yes
sercomm-printserver factory-default --yes --confirm-name NAME
sercomm-printserver password set | clear --yes
sercomm-printserver set-ip --yes --confirm-name NAME
sercomm-printserver print lpd | raw --queue L1 FILE
sercomm-printserver arp assign-ip --mac MAC --ip IP --yes
sercomm-printserver arp factory-reset --mac MAC --ip IP --yes --confirm-name SCxxxxxx
```

## Testing

- Unit and contract tests run everywhere, the protocol adapters against small local servers
  on 127.0.0.1 that speak the device's dialect.
- End-to-end tests against a real device are opt-in: pytest marker `device`, enabled only
  with `SERCOMM_E2E=1` and a local, gitignored `test-device.json` (template:
  `test-device.example.json`). They snapshot `CONFIG` before any write and restore it
  afterwards. Tiers: read-only; low-risk writes (a harmless key, password set and clear);
  an IP change to a free address and back; a temporary static ARP alias. Factory default and
  the ARP trick with `SETIP`/`DEFAULTC` never run automatically. RAW print ports are not
  touched until a printer is attached (marker `printer`), because a bare connect occupies the
  port.
