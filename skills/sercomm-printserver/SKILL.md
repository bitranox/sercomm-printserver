---
name: sercomm-printserver
description: Use when managing, configuring or printing to a SerComm-based network print server - the Sercom PS301 and its TRENDnet (TE-310, TE100-P1P, TEW-P1U1P), Perle IOPRINT+, Netgear PS110/PS113/PS101 and Linksys PPSX1/EPSX3 twins - that greets FTP with "220 Print Server Ready.": finding one on the network, reading its status, queues or CONFIG, changing its IP, DHCP or password, restarting it, printing by LPD or RAW, or recovering one whose address or password is lost (the vendor's "ARP trick").
---

# sercomm-printserver

Drive the device with the `sercomm-printserver` CLI (or the Python library of the same name).
Never script FTP `get RESET` / `get DEFAULTC` / `get PASSRESET` / `get SETIP` by hand: on these
devices a GET of those files is an ACTION, not a read.

```bash
uvx --exclude-newer "7 days" sercomm-printserver --help     # or: uv tool install sercomm-printserver
```

Run `sercomm-printserver <command> --help` for every option; this page gives what `--help`
cannot.

## Pick the command

| Goal                                  | Command                                                                    |
|---------------------------------------|----------------------------------------------------------------------------|
| Find devices on this host's networks  | `discover` (or `discover --network 192.0.2.0/24`)                          |
| Name, MAC, firmware, addresses        | `device-info --host H`                                                     |
| Port state and printer status         | `status --host H`                                                          |
| LPD queue state (sends no print data) | `queue L1 --host H`                                                        |
| Whole configuration / one value       | `device-config show` / `device-config get IP_ADDR`                         |
| Change settings                       | `device-config set DHCP_MODE=Disable IP_ADDR=192.0.2.60 --yes`             |
| Back up / restore the configuration   | `device-config export FILE` / `device-config import FILE --yes`            |
| Restart                               | `reset --yes`                                                              |
| Print                                 | `print lpd L1 FILE` (preferred) or `print raw 1 FILE`                      |
| Set the login password                | `password set --yes` (hidden prompt or `--from-file FILE`)                 |
| Clear the login password              | `password clear --yes --confirm-name NAME`                                 |
| Keep the current address as static    | `store-ip --yes --confirm-name NAME`                                       |
| Factory settings (IP becomes 0.0.0.0) | `factory-default --yes --confirm-name NAME`                                |
| Device has no usable address          | `arp reach / assign-ip / factory-reset --mac MAC --ip FREE_IP` (as admin;  |
|                                       | the last two with `--yes`, `factory-reset` also `--confirm-name SCxxxxxx`) |

Every device command except `arp` (which takes `--ip`) takes `--host`, overriding `[device] host`
from the configuration (`SERCOMM_PRINTSERVER___DEVICE__HOST` in the environment). Commands that
change the device (`device-config set`/`import`, `reset`, `password`, `store-ip`,
`factory-default`, `arp assign-ip`/`factory-reset`) show what they would do and exit 77 without
`--yes`. The rows above that show `--confirm-name` need both, the name being the device's
`server_name` or `default_name` from `device-info`. Reading and printing need neither.

## Output and exit codes

Every device command, `arp` and `discover` included, takes `--json` (indented) or `--json-bare`
(one line) and then writes valid JSON on stdout, success (`ok`, `command`, `data`, `skipped`) or
failure (`ok`, `command`, `error`, `message`). `skipped` names what a partial answer left out,
such as a network too large for `discover` to sweep:

```json
{"ok": true, "command": "firmware", "data": {"host": "192.0.2.52", "firmware": "6022"}, "skipped": []}
{"ok": false, "command": "reset", "error": "ConfirmationRequiredError", "message": "reset changes the device; pass --yes to do it"}
```

Branch on the exit code, never on the message text; where one code has two causes, the
envelope's `error` names the exception (77: `ConfirmationRequiredError` for a missing
confirmation, `AuthenticationRequiredError` for a login the device wants):

| Code | Meaning                                                                              |
|------|--------------------------------------------------------------------------------------|
| 0    | done                                                                                 |
| 13   | this host lacks a right: `arp` writing the ARP table, `config-deploy` a system dir   |
| 22   | invalid argument (malformed address, unknown key, empty RAW data)                    |
| 69   | device did not answer (refused, timed out, did not come back after a restart)        |
| 76   | device answered something this firmware family does not send                         |
| 77   | refused: missing `--yes` / wrong `--confirm-name`, or the device wants a login (530) |
| 78   | configuration error (no `--host` and no `[device] host`)                             |

## Ports, queues and printers

A device has two parallel ports `P1`, `P2` and a serial `SP` (one-port models: `P1` only).
LPD queues are `L1`..`L8` (one-port models `L1`..`L3`); which port a queue feeds is in the
device's CONFIG - on a factory PS301 `L1`/`L4`/`L7` -> P1, `L2`/`L5`/`L8` -> P2, `L3`/`L6` -> SP,
and the queue `lp` -> P1. Read it instead of assuming: `device-config get L3_PROUT` answers
`SP` (keys `L1_PROUT`..`L8_PROUT`).

RAW ports belong to the logical printers `L1`..`L3` only: `print raw 1|2|3` uses port
`raw_port_base` + 0/1/2 (`[device] raw_port_base`, default 9100), and the data goes wherever
that printer is routed, exactly like an LPD job (measured on a PS301, firmware 6022: with
`L1_PROUT=P2`, port 9100 fed P2). That firmware also opens the vendor's DSI sockets
4010/4020/4030 for the same three printers; they step by 10, so `raw_port_base` cannot express
them. `print raw 4` and above is refused (exit 2). Prefer `print lpd`, which reaches all eight.

**Never send a test byte to a RAW port** - no port probe, no `echo > /dev/tcp/H/9100`, no empty
test print. Data that no printer takes stays queued: the port reads "Printing / Direct Socket"
until the device restarts (`reset --yes` clears it). `print raw` refuses empty data (exit 22).
To check a port, read `status`: each port's state (`Idle` or `Printing`), its type and the
printer status the device reports (`Offline` with no printer attached or switched off).
Without a printer, `status` is as far as a check can go.

## Passwords and logins

- Factory state: no password. The FTP login is the device's name (`BOX_NAME`, else the default
  name `SC` + last six MAC hex digits); `[device] login` empty means "ask the device first".
- After `password set`, later commands need it: set `[device] password` in the configuration or
  `SERCOMM_PRINTSERVER___DEVICE__PASSWORD` in the environment - never on the command line.
- **A password does not protect the device.** `PASSRESET` (`password clear`) and the other
  action files work over FTP without logging in (measured on firmware 6022). Treat the device as
  open to anyone on its network.

## Changes and restarts

`device-config set` / `import` and `reset` restart the device and **wait** until it is back
(by its SNMP uptime, up to 120 s), so the next command can run at once. When the change moves
the IP, it waits at the NEW address and reports it as `reachable_at` - pass that as `--host`
next; `[device] host` is not rewritten. `store-ip`, `factory-default` and `password` do not
wait (whether SETIP restarts the device is not measured). With DHCP switched on
nothing waits (the address is the DHCP server's choice). `--no-apply` / `--no-wait` skip that.
The device refuses connections for about 0.1 s after every FTP session; the tool retries that
itself, so a script need not. For the same reason a reachability check of your own is no
restart signal.

## Production devices

`discover` only reads the FTP greeting and says QUIT, and never logs in, because some firmware
(6A10) answers anything more with garbage and has been seen to stop serving until power-cycled.
Run reads and writes only against the device you mean; never sweep a production network with
logins or test prints.

## ARP trick: a device without a usable address

The device answers any IP this host maps to its MAC. `arp` writes that static ARP entry, talks
to the device at the borrowed address, and removes the entry again in every case. It needs root
or `CAP_NET_ADMIN` on Linux, root on macOS, Administrator on Windows (exit 13 without).

- `--ip` must be FREE (an address that answers is refused) and inside one of this host's
  subnets (the entry is not a route).
- The device must be on this host's Ethernet segment; ARP does not cross a router.
- All three take `--mac` and `--ip`; `--mac` in any common spelling (`00:c0:02:12:34:56`,
  `00-C0-02-12-34-56`, `00c002123456`, `00c0.0212.3456`). The check uses the device's
  `default_name` from PSINF, which a renamed `BOX_NAME` does not change.
- `arp reach` only reads PSINF and checks that the device's default name matches `--mac`.
- `arp assign-ip --yes [--netmask M] [--gateway G]` stores `--ip` as the device's static
  address (DHCP off), keeps the device's own netmask and gateway unless given, restarts it and
  waits for it there, like `device-config set` (`data.write.reachable_at`). It checks the
  device's name itself; `arp reach` first is optional.
- An `--ip` that already answers (an ARP request where this host may send one, else its ARP
  cache) is refused with exit 22 before anything is written. `arp` always waits; it has no
  `--no-wait`.
- `arp factory-reset --yes --confirm-name SCxxxxxx` (the default name derived from the MAC).

## Python

```python
from sercomm_printserver import DeviceEndpoint, PrintJob, open_print_server

server = open_print_server(DeviceEndpoint(host="192.0.2.52"))  # login/password/timeout optional
server.print_lpd("L1", PrintJob(data=open("page.prn", "rb").read(), name="page"))
print(server.info().firmware_version, [p.port for p in server.status()])
```

`discover_print_servers()`, `PrintServer.read_config()` / `write_config()` / `reset()`, and
`arp_trick` with `IpscoutNeighborTable` cover the rest; every failure raises one of the
exceptions exported by the package (`DeviceUnavailableError`, `ConfirmationRequiredError`, ...).
`help(sercomm_printserver.PrintServer)` lists each method with its `Raises`.
