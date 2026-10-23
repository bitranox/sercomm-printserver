# Changelog

All notable changes to this project will be documented in this file following
the [Keep a Changelog](https://keepachangelog.com/) format.


## [Unreleased]

### Added

- Project created from `bitranox_template_py_cli` and renamed to `sercomm-printserver`.
- `docs/Manual-PS301.md`: what is known about the SerComm PS301 print server family.
- Device commands for the SerComm print-server family: `discover` (by the FTP greeting, no login),
  `device-info`, `firmware`, `status`, `queue`, `device-config show/get/set/export/import`, `reset`,
  `password set/clear`, `store-ip`, `factory-default`, and `print lpd/raw`. Every one answers with
  `--json` / `--json-bare`; changes need `--yes`, the dangerous ones also `--confirm-name`.
- `arp reach/assign-ip/factory-reset`: reach a device by its MAC through a borrowed address (the
  vendor's ARP trick), with the static ARP entry written natively through ipscout and removed
  again in every case. Needs root or `CAP_NET_ADMIN`, root on macOS, Administrator on Windows
  (exit 13 without).
- A typed model of the device's CONFIG file, `docs/config-keys.md` with the keys of each model
  and firmware version, and writes that restart the device and wait for it by its SNMP uptime.
- Python library surface: `open_print_server`, `discover_print_servers`, `PrintServer`,
  `DeviceEndpoint`, `PrintJob`, `arp_trick`, `IpscoutNeighborTable` and the domain exceptions.
- Claude Code plugin with the `sercomm-printserver` skill.
- End-to-end tests against a real device (`-m device`, opt-in), which save the device's
  configuration before any change and restore it.
