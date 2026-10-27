# Module Reference: sercomm-printserver

## Status

v0.2.0. Describes the modules as they are in the source tree; update it with every change that
adds a module, a CLI command or a public name.

## Links & References

**Repository:** https://github.com/bitranox/sercomm-printserver
**Documentation:** README.md, INSTALL.md, CONFIG.md, DEVELOPMENT.md, CONTRIBUTING.md, CHANGELOG.md
**Device notes:** docs/Manual-PS301.md, docs/config-keys.md, docs/adr/0001-memory-adapters-in-src.md
**Public API:** src/sercomm_printserver/__init__.py (`__all__`; every name resolving is checked by tests/test_public_api.py)

## Problem Statement

SerComm-based network print servers (PS301 and OEM variants) are configured through a handful of
virtual files over FTP and TFTP, report port state on a Telnet console, and print over LPD or RAW
sockets. Each protocol has firmware quirks, the CONFIG file is a numbered line format, and a
device with an unknown address can only be reached by mapping a borrowed IP to its MAC.

## Solution Overview

1. **Typed CONFIG** - `render_config(parse_config(text)) == text` for a device-produced file;
   every write shows the diff first.
2. **One use-case object** - `PrintServer` reads, configures, restarts, guards destructive
   actions and prints, over injected protocol ports.
3. **Discovery** - finds devices by their FTP greeting `220 Print Server Ready.`.
4. **ARP trick** - reaches a device by MAC through a static neighbour entry held for one call.
5. **CLI** - every device command answers for a person or as a JSON envelope, with exit codes
   that do not depend on the output format.

## Architecture Integration

```
composition/   wires adapters to ports (build_production, build_testing)
    | imports
adapters/      ftp, telnet, tftp, lpd, raw, snmp, discovery, neighbors, config, logging, cli, memory
    | imports
application/   PrintServer, discovery, arp_trick, ports (Protocols)
    | imports
domain/        pure models and parsers: no I/O, logging or frameworks
```

**Import contracts** (`tool.importlinter`, run by `lint-imports`):
"Domain is pure (no adapter dependencies)" forbids `domain` from importing `adapters` or
`composition`; "Clean Architecture layers" enforces composition -> adapters -> application ->
domain.

**Runtime dependencies:** rich-click, click, lib_cli_exit_tools, lib_log_rich, python-dotenv,
lib_layered_config, pydantic, orjson, ipscout. Python >= 3.10.

## Core Components

### Domain (`src/sercomm_printserver/domain/`)

| Module                | Contents                                                                              |
|-----------------------|---------------------------------------------------------------------------------------|
| `config_lines.py`     | `ConfigLine`, `split_lines`, `join_lines`: the `NNNN TOKEN:VALUE` line format         |
| `config_catalogue.py` | Line numbers and tokens of the modelled CONFIG parameters                             |
| `config_types.py`     | Value types (`Text15`, `Byte`, `BaudRate`, `Parity`, `LptMode`, ...)                  |
| `config_model.py`     | `DeviceConfig` and its sections (`TcpIp`, `Smb`, `Snmp`, `NetWare`, ...)              |
| `config_reader.py`    | `read_config`: lines to `DeviceConfig`                                                |
| `config_writer.py`    | `write_config`: `DeviceConfig` back to lines                                          |
| `config_codec.py`     | `parse_config`, `render_config`, `diff_config`, `with_value`, `ConfigChange`          |
| `device_files.py`     | `ReadableFile`, `WritableFile`, `DeviceAction` (RESET, DEFAULTC, PASSRESET, SETIP)    |
| `device_info.py`      | `DeviceInfo` from PSINF and the FTP `SYST` reply; MAC helpers                         |
| `endpoint.py`         | `DeviceEndpoint` (where and how to reach one device), `PrintJob`, `Port`              |
| `port_status.py`      | `PortStatus`, `PortState`, `PortType`, `PrinterStatus`, `parse_monitor`               |
| `neighbor.py`         | `AddressHolder`, `LookupMethod`: who holds an address, asked by ARP or from the cache |
| `enums.py`            | `OutputFormat`, `DeployTarget`                                                        |
| `errors.py`           | The exception types (see Exit Codes)                                                  |

### Application (`src/sercomm_printserver/application/`)

* `print_server.py` - `PrintServer` (firmware_version, info, status, read_config, queue_state,
  plan_config, write_config, reset, set_password, clear_password, store_ip, factory_default,
  print_lpd, print_raw), `DevicePorts`, `ConfigWriteResult`.
* `discovery.py` - `discover(scanner, networks=, timeout=)` returning `DiscoveryReport` of
  `DiscoveredDevice`; `LocalScope` (the default sweep plan the scanner port returns),
  `MAX_HOSTS`, `PRINT_SERVER_GREETING`.
* `arp_trick.py` - `borrowed_address`, `reach`, `assign_ip`, `factory_reset`, `ArpResult`.
* `ports.py` - the Protocols below.

| Protocol                                                                    | Implemented by (production)          |
|-----------------------------------------------------------------------------|--------------------------------------|
| `FtpPort`                                                                   | `adapters/ftp/client.py` `FtpClient` |
| `TelnetPort`                                                                | `adapters/telnet/client.py`          |
| `TftpPort`                                                                  | `adapters/tftp/client.py`            |
| `LpdPort`                                                                   | `adapters/lpd/client.py`             |
| `RawPort`                                                                   | `adapters/raw/printer.py`            |
| `UptimePort`                                                                | `adapters/snmp/uptime.py`            |
| `HostScanner`                                                               | `adapters/discovery/scanner.py`      |
| `NeighborTable`, `OpenNeighborTable`                                        | `adapters/neighbors/table.py`        |
| `OpenPrintServer`                                                           | `composition.open_print_server`      |
| `GetConfig`, `GetDefaultConfigPath`, `DeployConfiguration`, `DisplayConfig` | `adapters/config/`                   |
| `InitLogging`, `CheckLoggingConfig`                                         | `adapters/logging/setup.py`          |

### Adapters (`src/sercomm_printserver/adapters/`)

* `ftp/`, `telnet/` (`client.py`, `iac.py`), `tftp/`, `lpd/`, `raw/`, `snmp/` - one protocol
  client each; `snmp` reads `sysUpTime` through ipscout's `read_snmp_system` (SNMPv1).
* `discovery/scanner.py` - `FtpBannerScanner`: FTP-port probes (ipscout's `grab_banners`, one
  connection per host), MACs and local networks, all through ipscout.
* `neighbors/table.py` - `IpscoutNeighborTable`: static ARP entries; maps ipscout's refusal to
  `HostPrivilegeError`. `holder_of` asks with an ARP request, reads the cache only when it
  cannot, and says which (`AddressHolder.method`).
* `config/` - layered configuration (`loader.py`, `deploy.py`, `display.py`, `overrides.py`) and
  `device_settings.py` (`DeviceSettings`, `resolve_endpoint`) for the `[device]` section.
* `logging/setup.py` - lib_log_rich initialization.
* `memory/` - in-memory doubles: `config.py`, `logging.py`, `device.py` (`FakeDevice`,
  `FakeTftp`), `discovery.py` (`FakeScanner`), `neighbors.py` (`FakeNeighborTable`).
* `cli/` - `root.py` (group), `main.py`, `context.py`, `config_load.py`, `envelope.py`
  (`Envelope`, `ErrorEnvelope`, `OutputMode`), `exit_codes.py`, `safe_console.py`,
  `typed_click.py`, `constants.py`, and `commands/` (`arp.py`, `config.py`, `device.py`,
  `device_config.py`, `discover.py`, `info.py`, `printing.py`, `_device.py` with the shared
  options and `exit_code_for`).

### Composition and entry points

* `composition/__init__.py` - `AppServices` (frozen container of every port), `build_production`,
  `build_testing(device=, scanner=, neighbors=)`, `open_print_server`.
* `entry.py` - console script `sercomm-printserver` (also `sercomm_printserver`).
* `__main__.py` - `python -m sercomm_printserver`.
* `__init__conf__.py` - static package metadata and `print_info`.

## CLI Commands

Root options: `--version`, `--traceback/--no-traceback`, `--profile NAME`,
`--set SECTION.KEY=VALUE` (repeatable), `--env-file FILE`, `-h/--help`. Device commands take
`--timeout`, `--json`, `--json-bare`, and all but `discover` and `arp` take `--host`; `discover`
takes `--network`, the `arp` commands `--mac`, `--ip` and `--interface` (`assign-ip` also
`--netmask`, `--gateway`). Changing commands need `--yes`, and `password clear`, `store-ip`,
`factory-default` and `arp factory-reset` also `--confirm-name`.

| Command                    | Purpose                                                               |
|----------------------------|-----------------------------------------------------------------------|
| `info`                     | Print package metadata                                                |
| `config`                   | Display the merged configuration                                      |
| `config-deploy`            | Deploy default configuration to app/host/user directories             |
| `config-generate-examples` | Write example configuration files                                     |
| `discover`                 | Find print servers by FTP greeting (`--network CIDR`, repeatable)     |
| `firmware`                 | Firmware version (FTP SYST; PSINF when SYST garbles it, as on 6A10)   |
| `device-info`              | PSINF self-description: names, MAC, firmware, addresses               |
| `status`                   | Per-port state and printer status (Telnet monitor)                    |
| `queue [QUEUE]`            | LPD queue state of L1..L8; sends no print data                        |
| `device-config show`       | Show the whole CONFIG                                                 |
| `device-config get`        | One parameter by token (`IP_ADDR`) or line number (`4000`)            |
| `device-config set`        | Change `KEY=VALUE` parameters; shows the diff, writes with `--yes`    |
| `device-config export`     | Save CONFIG exactly as the device sends it                            |
| `device-config import`     | Write an exported CONFIG; shows the diff, writes with `--yes`         |
| `reset`                    | Restart and wait until the device answers again (`--no-wait`)         |
| `password set`             | Set the login password from `--from-file` or a hidden prompt          |
| `password clear`           | Clear the login password (PASSRESET)                                  |
| `store-ip`                 | Store the current address as static IP (SETIP)                        |
| `factory-default`          | Restore factory settings (stored IP 0.0.0.0 with DHCP on, name empty) |
| `print lpd QUEUE SOURCE`   | Send a file or stdin to an LPD queue (`--job-name`)                   |
| `print raw PRINTER SOURCE` | Send a file or stdin to the RAW port of logical printer 1..3          |
| `arp reach`                | Read the identity of the device behind `--mac` at borrowed `--ip`     |
| `arp assign-ip`            | Store `--ip` as static address (DHCP off) and restart there           |
| `arp factory-reset`        | Restore factory settings of the device behind `--mac`                 |

## Exit Codes

`ExitCode` in `adapters/cli/exit_codes.py`; device commands map errors through `exit_code_for`
in `adapters/cli/commands/_device.py` (first match wins, anything else exits 1).

| Code | Name                 | Raised for                                                                                                                                               |
|------|----------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------|
| 0    | `SUCCESS`            | Command completed                                                                                                                                        |
| 1    | `GENERAL_ERROR`      | `NeighborTableError`, or any unmapped failure                                                                                                            |
| 2    | `FILE_NOT_FOUND`     | click's usage error (bad option or missing argument); no command raises it                                                                               |
| 13   | `PERMISSION_DENIED`  | `HostPrivilegeError` (no right to change the ARP table), `UnverifiedAddressError` (no ARP request possible, cache knows nothing); config-deploy refusals |
| 22   | `INVALID_ARGUMENT`   | `ValueError`, including `ConfigFormatError`; config section not found                                                                                    |
| 69   | `DEVICE_UNAVAILABLE` | `DeviceUnavailableError`: refused, timed out, no route                                                                                                   |
| 76   | `PROTOCOL_ERROR`     | `DeviceResponseError`: the device answered in an unexpected form                                                                                         |
| 77   | `REFUSED`            | `ConfirmationRequiredError`, `AuthenticationRequiredError`                                                                                               |
| 78   | `CONFIG_ERROR`       | `ConfigurationError`: configuration missing, not loadable or invalid                                                                                     |
| 110  | `TIMEOUT`            | Defined in the enum; no command exits with it                                                                                                            |
| 130  | `SIGNAL_INT`         | SIGINT (translated by lib_cli_exit_tools)                                                                                                                |
| 141  | `BROKEN_PIPE`        | Output pipe closed                                                                                                                                       |
| 143  | `SIGNAL_TERM`        | SIGTERM                                                                                                                                                  |

## Implementation Details

**Envelope:** with `--json` (indented) or `--json-bare` (one line) stdout carries only
`{ok, command, data, skipped}`; a failure is an `ErrorEnvelope` with the same `ok` and `command`
keys. Messages for a person go to stderr.

**Configuration writes:** `PrintServer.write_config` uploads only when `diff_config` finds a
change, verifies the upload, and with `apply` restarts the device and reports where it is
reachable (`ConfigWriteResult`).

**Restart wait:** the device restarts about 5 s after the triggering session ends. `reset` waits
until an SNMP uptime read afterwards is no longer than the time since the trigger, then until FTP
answers again, for at most 120 s.

**ARP trick:** the static neighbour entry lives only inside `borrowed_address`; the device is
then spoken to over FTP at the borrowed address, and the entry is removed in every case.
`factory_reset` refuses unless the PSINF default name matches both `--mac` and `--confirm-name`.

**`[device]` defaults** (`adapters/config/defaultconfig.d/50-device.toml`): `host = ""`,
`login = ""`, `password = ""`, `timeout = 10.0`, `raw_port_base = 9100` (L2 and L3 use the next
two ports; L4..L8 have no RAW port).

## Testing Approach

All under `tests/`:

* Protocol adapters against loopback fakes (`fake_ftp_server.py`, `fake_telnet_server.py`,
  `fake_tftp_server.py`, `fake_lpd_server.py`, `fake_raw_server.py`): the `test_adapter_*.py`
  modules (ftp, telnet, tftp, lpd, raw, snmp, neighbors).
* Use cases over in-memory adapters: `test_print_server.py`, `test_discovery.py`,
  `test_arp_trick.py`, `test_config_codec.py`, `test_device_reports.py`, `test_ports.py`.
* CLI: `test_cli_device.py`, `test_cli_arp.py`, `test_cli_exit_codes.py`,
  `test_cli_main_exit.py`, `test_cli_core.py` and the config/override `test_cli_*.py` modules.
* Real device: `test_e2e_device.py`, marker `device` (needs `SERCOMM_E2E=1` and
  `test-device.json`); marker `printer` also needs `SERCOMM_E2E_PRINTER=1`.

**Doctests:** `--doctest-modules`. **Platform markers:** `os_agnostic`, `os_windows`, `os_macos`,
`os_posix`, `os_linux`; `local_only`, `integration`. **Coverage gate:** `fail_under = 80`.

## Known Limitations

* `PrintServer` triggers actions over FTP. The PS301 does take `RESET` over TFTP but refuses
  `PASSRESET`, and TFTP reports nothing back about the result.
* `print raw` reaches only L1..L3: the RAW ports belong to those three logical printers.
* `password clear` works without a login on firmware 6022: a password does not stop anyone on
  the network from clearing it.
* `password set` accepts at most 19 printable ASCII characters.
* The ARP trick needs the right to change this host's neighbour table (exit 13 otherwise).

## Security Considerations

* The password is never taken from the command line (`--from-file` or a hidden prompt) and
  `config` shows the configured `password` redacted.
* Destructive commands refuse (exit 77) without `--yes` and, where listed, `--confirm-name`.
* Discovery reads only the FTP greeting; it never logs in and never prints.

## Quick Reference

```python
from sercomm_printserver import DeviceEndpoint, PrintJob, discover_print_servers, open_print_server

report = discover_print_servers(networks=["192.0.2.0/24"])
server = open_print_server(DeviceEndpoint(host="192.0.2.52"))
print(server.info().firmware_version)
server.print_lpd("L1", PrintJob(data=b"hello\r\n\f", name="greeting"))
```

```bash
sercomm-printserver discover --network 192.0.2.0/24
sercomm-printserver status --host 192.0.2.52 --json
sercomm-printserver device-config set --host 192.0.2.52 CONTACT="printer room" --yes
sercomm-printserver arp reach --mac 00:00:5e:00:53:01 --ip 192.0.2.200
```
