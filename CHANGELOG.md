# Changelog

All notable changes to this project will be documented in this file following
the [Keep a Changelog](https://keepachangelog.com/) format.


## [Unreleased]

### Added

- `PrintData` (exported from the package root): a print job's bytes, read from their source in
  pieces of at most 64 KiB, built with `PrintData.of(bytes)`, `PrintData.from_path(path)` or
  `PrintData.from_stream(stream)`. `print lpd` and `print raw` now stream the file or stdin
  instead of reading it whole, so a job's size no longer adds to peak memory (measured: about
  1x the job before, under 1 MiB at 64 and 128 MiB after).
- `print lpd` from a pipe spools the data to a temporary file first, because LPD sends the size
  ahead of the data. A spool that cannot be written raises `SpoolError` (exit 74) before the
  device is contacted; a file that changes size while it is sent raises
  `PrintSourceChangedError` (exit 65) and leaves the job without its end-of-file byte.
- `check` (library: `PrintServer.check`) tells a wedged port from a busy one. A port reading
  `Printing`, occupied by `Direct Socket`, 0 bytes serviced, gets a bare connect with no data on
  every RAW port routed to it: when all of them accept, the port is `wedged` (every later job to it
  is lost until a restart); when one refuses, a client `held` it. Other ports read `idle` or
  `printing`. It exits 3 when a port is wedged, 0 otherwise.
- `check --reset --yes` (library: `PrintServer.reset_if_wedged`) restarts the device only when a
  port is wedged, waits for it, and checks again; it exits 3 when the port is still wedged.
  `--reset` without `--yes` is refused.
- `scripts/ps301_wedge_probe.py` reproduces the wedge on a real device, with and without the
  drain wait, in alternating trials, and logs each one as a JSON line. Every trial prints its job,
  so it runs only with `--confirm-print`.
- `PortStatus.occupant` gives the protocol `OCCUPIED BY` names as an `Occupant` (`Direct Socket`,
  `LPD`), and None for a free port or any other holder; `occupied_by` keeps the text.

### Changed

- `PrintJob.data` is a `PrintData`; plain bytes are still accepted and wrapped, and in-memory data
  compares equal to its bytes, so `PrintJob(data=b"...")` and `job.data == b"..."` keep working.
  `len(job.data)` and the truth value of `job.data` no longer work: use `job.data.size`.
- `RawPort.send` takes `PrintData` or bytes and returns the number of bytes sent; `LpdPort.submit`
  returns the size of the data file sent. `PrintServer.print_raw` and `print_lpd` return the same
  counts, and `print_raw`/`print_raw_verified` take `PrintData` or bytes. A RAW connection that
  breaks while a pipe is sent says the job's size is unknown instead of giving a total.
- `print raw` reads the device configuration first (one FTP session, about 1.2 s) and, for a
  logical printer routed to the serial port `SP`, keeps the connection open until the job has
  crossed the serial line at the port's baud rate (plus 0.25 s) before it closes. A RAW connection
  opened while the device still passes the previous job on loses its data and wedges the port; a
  printer on a parallel or USB port gets no wait.
- `print raw --verify` names the cause in its exit 75 and 110 messages: a wedged port
  (`check --reset --yes` clears it) or another client holding the port. A port still printing
  keeps the old wording.
- The empty-data refusal of `print raw` now reads "an empty job can leave the RAW port blocked
  for minutes": a bare connect with no data was measured harmless.
- `sercomm_printserver.adapters.raw` exports `connect_retrying_refusals`.

### Fixed

- `display_config` takes its `output_format` as the plain value too (`"json"`), as an untyped caller passes it, instead of failing with `AttributeError: 'str' object has no attribute 'value'`.

## [0.3.0] - 2026-11-02

### Added

- `print raw --verify` (library: `PrintServer.print_raw_verified`) waits for the port the logical
  printer is routed to to read `Idle`, sends, and waits again, each for up to `--verify-timeout`
  seconds (default 30). A plain `print raw` succeeds once the device took the bytes: a port held by
  another job accepts a new one, and a job that blocks the port afterwards goes unnoticed. A port
  still busy before the send exits 75 with `PortBusyError`, nothing sent. After the send it exits
  110 with `JobNotDrainedError`, which always means the data was sent; exit 69 comes only from
  before or during the send. `Idle` means the port is free, not that a page came out. Without
  `--verify` the command and its JSON answer are unchanged; with it the answer adds `idle_port`.
- The package root exports `PortBusyError` and `JobNotDrainedError`, and the enums a `PortStatus`
  holds: `PortId`, `PortState`, `PortType` and `PrinterStatus`. They were importable only from
  internal modules.

### Fixed

- `notebooks/Quickstart.ipynb` installs the checkout it runs in, so CI's "Execute notebooks" job
  tests the commit under test. It used to install `git+https://github.com/...` every time, which is
  the pushed default branch, so a pull request's notebook run tested the code already there.
  Outside a checkout (a downloaded notebook) it still installs from GitHub.

## [0.2.2] - 2026-10-30

### Changed

- Requires `lib_log_rich>=8.1.2`, `lib_layered_config>=7.6.1` and `ipscout>=2.5.4`.
- The skill describes the RAW connect retry, the `--timeout` it needs, and how to tell a RAW port
  stuck refusing from a device that is down.

### Fixed

- `print raw` (and `RawPrinter.send`) retries a refused connect for up to 3 s, never longer than the
  timeout, before reporting the device unreachable. A PS301 RAW port refuses a new connection for
  about 1-2 s after the previous job closed, so the second of two jobs sent back to back failed
  although nothing was wrong. Other connect errors still fail at once.
- When a RAW port refuses for the whole retry window, the error now says so and that a restart
  (`reset`) clears a port stuck refusing. A PS301 has been measured refusing every RAW connect for
  minutes while `status` showed the port idle, so the message is the only place this shows.

## [0.2.1] - 2026-10-27

### Changed

- Requires `lib_log_rich>=8.0.1`. A key in the `[lib_log_rich]` section that lib_log_rich does
  not know is now refused by name (`lib_log_rich.<key>: Extra inputs are not permitted`) and
  logging starts with the defaults, as for any other refused setting. It used to be ignored, so a
  misspelled setting silently kept its default.
- Requires `ipscout>=2.5.2`.

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

## [0.2.0] - 2026-10-26

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

## [0.1.0] - 2026-10-24

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
