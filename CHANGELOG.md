# Changelog

All notable changes to this project will be documented in this file following
the [Keep a Changelog](https://keepachangelog.com/) format.


## [Unreleased]

### Changed

- Requires `lib_log_rich>=8.0.1`. A key in the `[lib_log_rich]` section that lib_log_rich does
  not know is now refused by name (`lib_log_rich.<key>: Extra inputs are not permitted`) and
  logging starts with the defaults, as for any other refused setting. It used to be ignored, so a
  misspelled setting silently kept its default.

### Fixed

- A device after a factory reset can be reached, read and written again (measured on a PS301,
  FW 6022). Its CONFIG holds an empty `BOX_NAME`, which was refused as out of range, so reading
  or writing its configuration failed; an empty name now parses and round-trips, and a non-empty
  one is still at most 19 characters without spaces. Its PSINF has an empty `Server Name:` line,
  which was taken for a section title, and an AppleTalk line `:LaserWriter`, which was refused
  as not `Key: Value`, so the ARP trick could not identify a reset device.
- A write the device refuses for want of a login, with no login configured, is retried with
  the default name (`SCxxxxxx`) when the server name is empty; it was retried with the empty
  name.
- An empty confirmation name no longer counts as repeating the empty server name of a reset
  device, so `factory-default`, `password clear` and `store-ip` refuse it there as everywhere.

## [0.2.0] 2026-10-26 18:46:01

### Changed

- `discover` probes port 21 through ipscout's `grab_banners` (requires `ipscout>=2.1.0`), still
  one connection per host. A server whose first line is not a `220` greeting is now also sent
  `QUIT` before the connection closes; it was closed without a word.
- `discover` without `--network` spends its 4096-address budget on the local networks with
  ipscout's `sweep_scope`, in the order the host reports them, and lists the rest as skipped.
  A host with several mid-size networks (three /21, 6138 addresses) was refused outright
  ("more than 4096; name a smaller network") and probed nothing. The skip note now reads
  `<network>: beyond the 4096-address budget, name it with --network`. Named `--network`
  values are still refused over 4096 addresses (exit 22). The `HostScanner` port answers
  `local_scope(limit=)` with a `LocalScope` instead of `local_networks()`.
- `SnmpUptime` reads `sysUpTime` through ipscout's `read_snmp_system` (requires
  `ipscout>=2.3.0`) instead of its own BER code. A silent agent, a closed SNMP port and a host
  that cannot be reached are `DeviceUnavailableError` ("gave no SNMP answer: silent" /
  "refused" / "unreachable"); an agent error or a reply without sysUpTime is
  `DeviceResponseError`.
- The ARP trick (`arp reach`, `arp assign-ip`, `arp factory-reset` and the `arp_trick`
  functions) refuses to borrow an address when this host could not send an ARP request and its
  ARP cache does not know the address: `UnverifiedAddressError`, exit 13, before anything is
  written. It used to fall back to the cache silently and borrow the address, although the cache
  knows only hosts already talked to (measured: it reported nobody at the address of a live print
  server). A cache entry naming another MAC is still refused, one naming the device still borrowed.
- `NeighborTable.mac_of` is now `holder_of`, returning an `AddressHolder` (the MAC or None, and
  `LookupMethod.ACTIVE` or `CACHE`); `IpscoutNeighborTable` asks through ipscout's
  `lookup_mac(active=True, fallback_to_cache=True)`, which falls back to the cache only when it
  cannot ask, instead of on any ipscout error. An address that is reached only through a router
  is a `ValueError` naming the router; the cache read used to report nobody holding it.

### Fixed

- `arp assign-ip` (and `arp_trick.assign_ip`) failed after the device had already moved: it
  waited 120 s for FTP at the borrowed address to go away and reported "did not go down". The
  SNMP agent does not answer at a borrowed address, so no uptime was read before the restart,
  and the FTP fallback never sees the short reboot (measured twice on a PS301). A restart is now
  recognised by an uptime, read at the address the device answers on afterwards, that is no longer
  than the time since the trigger; no uptime from before the trigger is needed. The same wait
  serves `reset` and configuration writes.
- `reset` and configuration writes on a device that never answers SNMP now fail with
  "gave no SNMP answer within 120 s, so its restart could not be confirmed" instead of watching
  FTP, which could not confirm the restart either and failed with "did not go down".
- The test suite no longer reads the app and host configuration layers of the machine it runs on.
  An autouse fixture points lib_layered_config's three app-root variables (`LIB_LAYERED_CONFIG_ETC`,
  `_MAC_APP_ROOT`, `_PROGRAMDATA`) at an empty directory under `tmp_path`, so a system-wide deploy
  (for example a `/etc/xdg/<slug>/config.d/99-*.toml`) can no longer fail tests locally while CI stays
  green. The subprocess tests in `test_display.py` and `test_logging_dotenv_isolation.py` dropped
  every `LIB_LAYERED_CONFIG*` variable and so read the real system layers; they now keep the redirect.
- The test suite no longer reads the developer's own user configuration layer. `user_layer_in_tmp_path`
  is now autouse and points the user layer (`XDG_CONFIG_HOME`, `LIB_LAYERED_CONFIG_MAC_HOME_ROOT`,
  `_APPDATA`, `_LOCALAPPDATA`) at an empty directory under `tmp_path`; `HOME` is no longer redirected,
  because git and uv read it.
- The doctests under `src/` no longer run against the machine's configuration layers: a fixture in
  `tests/conftest.py` never reaches them. The two layer redirects now live in a rootdir `conftest.py`,
  their variable lists in `tests/layer_roots.py`; pyproject sets `testpaths` to include `src` and
  `tests` (which keeps the root `conftest.py` out of doctest collection), adds `tests` to `pythonpath`
  and pyright's `extraPaths`, and gives pyright an execution environment rooted at `tests/`. A test
  checks that every doctest collected from `src/` gets both redirects.

## [0.1.0] 2026-10-24

### Added

- Project created from `bitranox_template_py_cli` and renamed to `sercomm-printserver`.
- `docs/Manual-PS301.md`: what is known about the SerComm PS301 print server family.
- Device commands for the SerComm print-server family: `discover` (by the FTP greeting, no login),
  `device-info`, `firmware`, `status`, `queue`, `device-config show/get/set/export/import`, `reset`,
  `password set/clear`, `store-ip`, `factory-default`, and `print lpd/raw`. Every one answers with
  `--json` / `--json-bare`; changes need `--yes`, the dangerous ones also `--confirm-name`.
  `print lpd/raw` report the transport (`lpd` or `raw`) and its queue or printer number as
  separate JSON fields. `discover` lists each local network it left out (more than 4096
  addresses) as a network string in `data.skipped`; the envelope's `skipped` says why.
- `arp reach/assign-ip/factory-reset`: reach a device by its MAC through a borrowed address (the
  vendor's ARP trick), with the static ARP entry written natively through ipscout and removed
  again in every case. Needs root or `CAP_NET_ADMIN`, root on macOS, Administrator on Windows
  (exit 13 without). `--mac` and `--ip` are checked before anything is written (exit 22).
- A typed model of the device's CONFIG file, `docs/config-keys.md` with the keys of each model
  and firmware version, and writes that restart the device and wait for it by its SNMP uptime.
- `print raw` reaches logical printers 1..3, the only ones with a RAW port. Measured on a PS301:
  9100-9102 and the vendor's 4010/4020/4030 both feed L1..L3 and follow each printer's routing.
- Python library surface: `open_print_server`, `discover_print_servers`, `PrintServer`,
  `DeviceEndpoint`, `PrintJob`, `arp_trick`, `IpscoutNeighborTable`, `MacAddress`,
  `normalise_mac` and the domain exceptions. The `arp_trick` functions take the borrowed address
  as `ip: IPv4Address`; MACs are normalised once, on entry. `DiscoveryReport.skipped` holds the
  left-out networks as `IPv4Network` values.
- Claude Code plugin with the `sercomm-printserver` skill.
- End-to-end tests against a real device (`-m device`, opt-in), which save the device's
  configuration before any change and restore it.

### Fixed

- TFTP on Windows: a device that closes its port during a transfer (as it does when a `RESET`
  restarts it) no longer reads as a broken transfer. Windows reports the ICMP "port unreachable"
  on the next read of the UDP socket; it is now treated like the silence Linux and macOS see.
