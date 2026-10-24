# Changelog

All notable changes to this project will be documented in this file following
the [Keep a Changelog](https://keepachangelog.com/) format.


## [Unreleased]

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
