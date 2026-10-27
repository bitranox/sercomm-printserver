---
name: sercomm-printserver
description: Use when managing, configuring or printing to a SerComm-based network print server - the Sercom PS301 and its TRENDnet (TE-310, TE100-P1P v1, TEW-P1U1P), Perle IOPRINT+, Netgear PS110/PS113 (PS101 suspected) and Linksys PPSX1/EPSX3 twins - that greets FTP with "220 Print Server Ready.": finding one on the network, reading its status, queues or CONFIG, backing up or restoring its CONFIG, changing its IP, DHCP or password, restarting it, printing by LPD or RAW, resetting it to factory settings and bringing it back afterwards, or recovering one whose address or password is lost (the vendor's "ARP trick").
---

# sercomm-printserver

Drive the device with the `sercomm-printserver` CLI (or the Python library of the same name).
Never script FTP `get RESET` / `get DEFAULTC` / `get PASSRESET` / `get SETIP` (or a TFTP `GET` of
them) by hand: on these devices a GET of those files is an ACTION, not a read. A TFTP `GET RESET`
restarts the device (measured).

```bash
uvx sercomm-printserver --help     # or: uv tool install sercomm-printserver
```

With a supply-chain cooldown (`--exclude-newer "7 days"`), also exempt the tool and its own
libraries, or uv finds no release for the first week after each one ("No solution found"). This
form runs (the same flags work on `uv tool install`):

```bash
uvx --exclude-newer "7 days" --exclude-newer-package sercomm-printserver=false \
    --exclude-newer-package ipscout=false --exclude-newer-package lib-log-rich=false \
    --exclude-newer-package lib-layered-config=false --exclude-newer-package lib-cli-exit-tools=false \
    sercomm-printserver --help
```

Run `sercomm-printserver <command> --help` for every option; this page gives what `--help`
cannot.

## Pick the command

| Goal                                  | Command                                                                    |
|---------------------------------------|----------------------------------------------------------------------------|
| Find devices on this host's networks  | `discover` (or `discover --network 192.0.2.0/24`)                          |
| Name, MAC, firmware, addresses        | `device-info --host H`                                                     |
| Firmware version only                 | `firmware --host H`                                                        |
| Port state and printer status         | `status --host H`                                                          |
| LPD queue state (sends no print data) | `queue L1 --host H` (`L1` is the default; `--long` for the long form)      |
| Whole configuration / one value       | `device-config show` / `device-config get IP_ADDR`                         |
| Change settings                       | `device-config set DHCP_MODE=Disable IP_ADDR=192.0.2.60 --yes`             |
| Back up / restore the configuration   | `device-config export FILE` / `device-config import FILE --yes`            |
| Restart                               | `reset --yes`                                                              |
| Print                                 | `print lpd L1 FILE` (preferred; `-` reads stdin, `--job-name`) or          |
|                                       | `print raw 1 FILE`                                                         |
| Set the login password                | `password set --yes` (hidden prompt or `--from-file FILE`)                 |
| Clear the login password              | `password clear --yes --confirm-name NAME`                                 |
| Keep the current address as static    | `store-ip --yes --confirm-name NAME`                                       |
| Factory settings (see below)          | `factory-default --yes --confirm-name NAME`                                |
| Device has no usable address          | `arp reach / assign-ip / factory-reset --mac MAC --ip FREE_IP` (as admin;  |
|                                       | the last two with `--yes`, `factory-reset` also `--confirm-name SCxxxxxx`) |

Every device command except `discover` and `arp` (which take `--network` and `--mac`/`--ip`)
takes `--host`, overriding `[device] host` from the configuration
(`SERCOMM_PRINTSERVER___DEVICE__HOST` in the environment). `--timeout` (0.1-600 s) overrides
`[device] timeout` (default 10 s). Commands that change the device (`device-config set`/`import`,
`reset`, `password`, `store-ip`, `factory-default`, `arp assign-ip`/`factory-reset`) exit 77
without `--yes`; `device-config set`/`import` also list the changes they would make. The rows
above that show `--confirm-name` need both, the name being the device's `server_name` or
`default_name` from `device-info`, in any case. Reading and printing need neither.

## Output and exit codes

Every device command, `arp` and `discover` included, takes `--json` (indented) or `--json-bare`
(one line) and then writes valid JSON on stdout, success (`ok`, `command`, `data`, `skipped`) or
failure (`ok`, `command`, `error`, `message`). The one exception is a usage error (an unknown
option, an out-of-range value, `print raw 4`): the command-line parser rejects it first, with exit
2, a usage message on stderr and nothing on stdout. `skipped` names what a partial answer left
out: `discover` without `--network` lists the local networks beyond its 4096-address budget there
(a named `--network` larger than that is refused, exit 22).

```json
{"ok":true,"command":"firmware","data":{"host":"192.0.2.52","firmware":"6022"},"skipped":[]}
{"ok":false,"command":"reset","error":"ConfirmationRequiredError","message":"reset changes the device; pass --yes to do it"}
```

Branch on the exit code, never on the message text; where one code has two causes, the
envelope's `error` names the exception (77: `ConfirmationRequiredError` for a missing
confirmation, `AuthenticationRequiredError` for a login the device wants; 13:
`HostPrivilegeError` or `UnverifiedAddressError`):

| Code | Meaning                                                                                      |
|------|----------------------------------------------------------------------------------------------|
| 0    | done                                                                                         |
| 1    | any other failure (the kernel refused the ARP entry for another reason, an unexpected error) |
| 2    | usage error, reported by the command-line parser (no JSON)                                   |
| 13   | this host lacks a right: `arp` writing the ARP table or sending an ARP request to check      |
|      | the address is free; `config-deploy` a system dir                                            |
| 22   | invalid argument (malformed address, unknown CONFIG key, empty RAW data, `--ip` held         |
|      | by another MAC or behind a router)                                                           |
| 69   | device did not answer (refused, timed out, did not come back after a restart, or gave no     |
|      | SNMP answer within 120 s, so its restart could not be confirmed)                             |
| 76   | device answered something this firmware family does not send, stored a value other than      |
|      | the one sent (see "Changes and restarts"), or held back an LPD acknowledgement past          |
|      | `--timeout` (a port without a printer)                                                       |
| 77   | refused: missing `--yes` / wrong `--confirm-name`, or the device wants a login (530) or      |
|      | rejected the password (531)                                                                  |
| 78   | configuration error (no `--host` and no `[device] host`, an unknown or invalid key in        |
|      | the configuration files)                                                                     |

Each of 69 and 76 carries one exception for all its causes (`DeviceUnavailableError`,
`DeviceResponseError`); after a 76 from a write, read the parameter back to see what the device
holds.

## Ports, queues and printers

A PS301 has two parallel ports `P1`, `P2` and a serial `SP`. Other models differ: PPSX1 and
TE100-P1P one parallel port, PS110 two parallel without `SP`, EPSX3 three parallel (`P3`),
TEW-P1U1P one parallel and one USB. The number of LPD queues differs too (`L1`..`L3`, `L1`..`L6`
or `L1`..`L8`), so on any model other than the PS301 read the layout from the device:
`status` lists its ports, `device-config get L1_PROUT` .. `L8_PROUT` its queues. Which port a
queue feeds is in the device's CONFIG - on the measured PS301 (FW 6022) `L1`/`L4`/`L7` -> P1,
`L2`/`L5`/`L8` -> P2, `L3`/`L6` -> SP and the queue `lp` -> P1, while a second PS301 (FW 6A10)
routed `L4`..`L8` to P1. Read it instead of assuming:
`device-config get L3_PROUT` answers `SP` (keys `L1_PROUT`..`L8_PROUT`).

RAW ports belong to the logical printers `L1`..`L3` only: `print raw 1|2|3` uses port
`raw_port_base` + 0/1/2 (`[device] raw_port_base`, default 9100), and the data goes wherever
that printer is routed, exactly like an LPD job (measured on a PS301, firmware 6022: with
`L1_PROUT=P2`, port 9100 fed P2). That firmware also opens the vendor's DSI sockets
4010/4020/4030 for the same three printers; they step by 10, so `raw_port_base` cannot express
them. `print raw 4` and above is refused (exit 2). Prefer `print lpd`, which reaches all eight.

**Never send a test job to a port without a printer**, by RAW or LPD - no port probe, no
`echo > /dev/tcp/H/9100`, no empty test print. Data that no printer takes stays queued: the port
reads "Printing / Direct Socket" (RAW) or "Printing / OCCUPIED BY: LPD" until the device restarts
(`reset --yes` clears it). An LPD job there is accepted, but the device holds back the
acknowledgement of its data, so `print lpd` fails after `--timeout` with exit 76. `print raw`
refuses empty data (exit 22).
To check a port, read `status`: each port's state (`Idle` or `Printing`), its type and the
printer status the device reports (`Offline` with no printer attached or switched off).
Without a printer, `status` is as far as a check can go.

## Passwords and logins

- Factory state: no password. The FTP login is the device's name (`BOX_NAME`, else the default
  name `SC` + last six MAC hex digits); `[device] login` empty means "ask the device first".
  CONFIG and PSINF are read without a login; an operation the device refuses with 530 is retried
  with its name and the configured password.
- After `password set`, writes need it: set `[device] password` in the configuration or
  `SERCOMM_PRINTSERVER___DEVICE__PASSWORD` in the environment - never on the command line. A wrong
  password is refused with 531 (exit 77). The login password is not part of CONFIG, so an export
  does not carry it.
- **A password does not protect the device.** `PASSRESET` (`password clear`) works over FTP
  without logging in (measured on firmware 6022), and the vendor manuals say RESET and DEFAULTC work
  over TFTP, which has no login. Treat the device as open to anyone on its network.
- `MAIL_PAS` (the POP3 mail password) always reads back as ten asterisks. Uploading the asterisks
  keeps the stored password (measured), so an export, edit and import cycle is safe, but an export
  cannot restore that password on another device or after a factory reset, and a password made
  only of asterisks cannot be set. Mail settings take effect without a restart.

## Changes and restarts

`device-config set` / `import` and `reset` restart the device and **wait** until it is back
(by its SNMP uptime, community `public`, up to 120 s), so the next command can run at once. When
the change moves the IP, it waits at the NEW address and reports it as `reachable_at` - pass that
as `--host` next; `[device] host` is not rewritten. A device whose SNMP agent does not answer
fails with exit 69 after 120 s although the change was applied. With DHCP switched on nothing
waits (the address is the DHCP server's choice). `device-config set`/`import --no-apply` store the
change without the restart (it takes effect at the next `reset --yes`); `reset --no-wait` returns
at once. `factory-default` and `password` do not wait. `store-ip` writes the address the device
runs on into CONFIG at once, without a restart (measured, FW 6022): it overwrites an `IP_ADDR`
written with `--no-apply`, and it does not adopt an address borrowed with `arp`.

After an upload the tool reads CONFIG back and compares it with what it sent. Rarely the device
stores a value other than the one sent (seen once in over 60 uploads); the command then fails
with exit 76 naming the parameter. Run it again: there is no automatic retry, so that a device
which really rewrites a value stays visible. `MAIL_PAS` is left out of that comparison.

The device refuses connections for about 0.1 s after every FTP session; the tool retries that
itself, so a script need not. For the same reason a reachability check of your own is no
restart signal.

## After a factory reset

Measured on a PS301 (FW 6022), 2026-10-27, with `factory-default` and `arp factory-reset`:

- The device restarts and answers again within about a minute. Neither command waits for that.
- CONFIG then holds `IP_ADDR:0.0.0.0`, `DHCP_MODE:Enable` and an empty `BOX_NAME`; PSINF's
  `Server Name:` is empty. With a DHCP server the device takes a lease (in the test network its
  OLD address), so the address alone does not show the reset happened: CONFIG's `IP_ADDR:0.0.0.0`
  does, and so does the empty server name of a device that had one. To wait for the device, poll
  `device-config get IP_ADDR` until it answers `0.0.0.0`, and give up after about two minutes.
  Without a DHCP server it has no usable address; reach it with `arp`.
- The FTP login is then the default name `SCxxxxxx` (the old name was accepted too), and
  `--confirm-name` takes only the default name.
- To bring it back: `device-config export FILE` BEFORE the reset, then `arp assign-ip --mac MAC
  --ip OLD_IP --yes`, then `device-config import FILE --yes --host OLD_IP`. That restores
  everything in CONFIG except the mail password (see `MAIL_PAS` above).

## Production devices

`discover` only reads the FTP greeting and says QUIT, and never logs in, because some firmware
(6A10) answers anything more with garbage and has been seen to stop serving until power-cycled.
Run reads and writes only against the device you mean; never sweep a production network with
logins or test prints.

## ARP trick: a device without a usable address

The device answers any IP this host maps to its MAC. `arp` writes that static ARP entry, talks
to the device at the borrowed address, and removes the entry again in every case. It needs root
on Linux (or both `CAP_NET_ADMIN`, to write the entry, and `CAP_NET_RAW`, to send the ARP request
that checks the address is free), root on macOS, Administrator on Windows (exit 13 without).

- `--ip` must be provably FREE, or held by the device itself (as when DHCP gave it back its old
  address), and inside one of this host's subnets (the entry is not a route).
  `--interface NAME|INDEX` picks the interface when more than one could hold it.
- The device must be on this host's Ethernet segment; ARP does not cross a router.
- All three take `--mac` and `--ip`; `--mac` in any common spelling (`00:c0:02:12:34:56`,
  `00-C0-02-12-34-56`, `00c002123456`, `00c0.0212.3456`). The check uses the device's
  `default_name` from PSINF, which a renamed `BOX_NAME` does not change.
- `arp reach` only reads PSINF and checks that the device's default name matches `--mac`.
- `arp assign-ip --yes [--netmask M] [--gateway G]` stores `--ip` as the device's static
  address (DHCP off), keeps the device's own netmask and gateway unless given, restarts it and
  waits for it there, like `device-config set` (`data.write.reachable_at`); it has no
  `--no-wait`. It checks the device's name itself; `arp reach` first is optional. Firmware
  without a `DHCP_MODE` line (PS301 FW 6A10) is refused (exit 22).
- An `--ip` that another MAC holds (by an ARP request, else this host's ARP cache) or that lies
  behind a router is refused with exit 22; one this host cannot check (no right to send an ARP
  request, and the cache does not know it) is refused as `UnverifiedAddressError`, exit 13. Both
  happen before anything is written.
- `arp factory-reset --yes --confirm-name SCxxxxxx` (the default name derived from the MAC)
  returns once the reset is triggered; see "After a factory reset".

## Python

```python
from sercomm_printserver import DeviceEndpoint, PrintJob, open_print_server

server = open_print_server(DeviceEndpoint(host="192.0.2.52"))  # login/password/timeout optional
server.print_lpd("L1", PrintJob(data=open("page.prn", "rb").read(), name="page"))
print(server.info().firmware_version, [p.port for p in server.status()])
```

A configuration change goes through the typed model: `with_value` validates one parameter in its
CONFIG spelling (an unknown key or a bad value raises `ConfigFormatError`), and `write_config`
uploads, reads back, restarts and waits (`apply=False` skips the restart). `reachable_at` is the
address the device answers at afterwards, `None` when DHCP decides it. The library asks no
`--yes`; `clear_password`, `store_ip` and `factory_default` require `confirm_name=`
(keyword-only, no default).

```python
from sercomm_printserver import with_value

result = server.write_config(with_value(server.read_config(), "CONTACT", "printer room"))
print(result.changes, result.written, result.applied, result.reachable_at)
```

`discover_print_servers()`, `parse_config()` / `render_config()`, `PrintServer.reset()`, and
`arp_trick` with `IpscoutNeighborTable` cover the rest; every failure raises one of the
exceptions exported by the package (`DeviceUnavailableError`, `ConfirmationRequiredError`, ...).
