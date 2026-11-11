# Python API

`sercomm-printserver` is a command line tool and a typed Python library. This page is the reference
for the library: how to reach a print server, read it, change it, print through it, and test your own
code without one. The command line tool is described in the [README](../README.md).

Every name on this page can be imported from `sercomm_printserver`, unless a section names another
module. That package's `__all__` is the public surface.

## Contents

- [Install and import](#install-and-import)
- [Reaching a device](#reaching-a-device)
- [The examples on this page run against a fake device](#the-examples-on-this-page-run-against-a-fake-device)
- [Reading](#reading)
- [Wedged ports](#wedged-ports)
- [Changing the configuration](#changing-the-configuration)
- [Restart, password, factory settings](#restart-password-factory-settings)
- [Printing](#printing)
- [Discovery](#discovery)
- [A device without a usable address: the ARP trick](#a-device-without-a-usable-address-the-arp-trick)
- [Exceptions](#exceptions)
- [Testing your code against the in-memory fakes](#testing-your-code-against-the-in-memory-fakes)
- [Application configuration](#application-configuration)

## Install and import

Python 3.10 or newer.

```bash
uv add sercomm-printserver          # into a uv project
pip install sercomm-printserver     # or with pip
```

The distribution is `sercomm-printserver`; the import package is `sercomm_printserver`:

```python
from sercomm_printserver import DeviceEndpoint, PrintJob, open_print_server
```

The package ships a `py.typed` marker, so pyright and mypy check your calls against its annotations.

## Reaching a device

`open_print_server(endpoint, *, raw_port_base=9100)` returns a `PrintServer` wired to the real
protocol clients (FTP, Telnet, TFTP, LPD, RAW sockets, SNMP). Building it opens no connection; every
method call opens its own and closes it again, so a `PrintServer` holds no session and can be kept
for as long as you like.

```python
# needs a real device
from sercomm_printserver import DeviceEndpoint, open_print_server

server = open_print_server(DeviceEndpoint(host="192.0.2.52", timeout=5.0))
print(server.info().firmware_version)
```

`DeviceEndpoint` is a frozen pydantic model. Change a field with `endpoint.model_copy(update={...})`.

| Field         | Default         | Meaning                                                                                 |
|---------------|-----------------|-----------------------------------------------------------------------------------------|
| `host`        | (required)      | IPv4 address or host name of the print server                                           |
| `login`       | `""`            | FTP login; empty means: try without, and on a 530 retry once with the device's own name |
| `password`    | `SecretStr("")` | FTP password (empty by factory default)                                                 |
| `timeout`     | `10.0`          | Seconds per network operation, `0 < timeout <= 600`                                     |
| `ftp_port`    | `21`            | FTP port                                                                                |
| `telnet_port` | `23`            | Telnet port (port status)                                                               |
| `tftp_port`   | `69`            | TFTP port                                                                               |
| `lpd_port`    | `515`           | LPD port                                                                                |

The device's FTP login is its name (`BOX_NAME`, or the default name `SCxxxxxx`). It serves `CONFIG`
and `PSINF` without a login, so most reads work with the defaults.

`raw_port_base` is the RAW (direct socket) port of logical printer `L1`; `L2` and `L3` use the next
two ports. Only `L1` to `L3` have a RAW port.

`timeout` bounds each connect, each send and each wait for a reply. It does not bound a whole
operation: a restart wait has its own limit of 120 s, and a verified print takes its own `timeout`
argument.

## The examples on this page run against a fake device

Every example below runs as written. Instead of a real print server they use the in-memory
`FakeDevice` the test suite uses, built once here; replace the last line with `open_print_server(...)`
to talk to a real device. [Testing your code against the in-memory fakes](#testing-your-code-against-the-in-memory-fakes)
describes the fake.

```python
from sercomm_printserver import DeviceEndpoint, PrintServer
from sercomm_printserver.adapters.memory.device import FakeDevice, FakeTftp
from sercomm_printserver.application.print_server import DevicePorts

CONFIG = """\
0001 BOX_NAME:PS_EXAMPLE
0011 IPXSPX_P:Disable
0012 TCPIP_P :Enable
0013 APTALK_P:Disable
0014 NETB_P:Disable
0030 BAUDRATE:9600
0031 STOPBITS:1
0032 PARITY  :None
0033 DATABITS:8
0034 HANDSHAK:BOTH
0100 L1_PROUT:P1
0101 L1_PREST:
0102 L1_POSTR:
0103 L1_CHGLF:No
0120 L2_PROUT:P2
0121 L2_PREST:
0122 L2_POSTR:
0123 L2_CHGLF:No
0140 L3_PROUT:SP
0141 L3_PREST:
0142 L3_POSTR:
0143 L3_CHGLF:No
4000 IP_ADDR:192.0.2.52
4001 GATEWAY:192.0.2.1
4002 MASK   :255.255.255.0
4010 TCP_INT:2
4011 TCP_CNT:254
4012 WINS_IP:0.0.0.0
4020 DHCP_MODE:Disable
"""

PSINF = """\
Hardware ID: 024010XXXX
Firmware Version: 6022
Protocol ID: 003F
Default Name: SC123456
Server Name: PS_EXAMPLE
TCP/IP Info:
  IP Address: 192.0.2.52
  Subnet Mask: 255.255.255.0
  Gateway Address: 192.0.2.1
"""

IDLE = """\
(P1)STATE: Idle
TYPE: Parallel
PRINTER STATUS: On-Line

(P2)STATE: Idle
TYPE: Parallel
PRINTER STATUS: On-Line

(SP)STATE: Idle
TYPE: Serial
PRINTER STATUS: On-Line
"""

device = FakeDevice(config=CONFIG, psinf=PSINF, monitor=IDLE)
ports = DevicePorts(ftp=device, telnet=device, tftp=FakeTftp(device), lpd=device, raw=device, uptime=device)
server = PrintServer(DeviceEndpoint(host="192.0.2.52"), ports, sleep=lambda seconds: None)
```

In this configuration `L1` prints on the parallel port `P1`, `L2` on `P2` and `L3` on the serial port
`SP`. Where an example expects an exception it prints the message, so the output shows what was
raised.

## Reading

None of these change anything on the device.

| Method                                     | Returns             | Reads                                                    |
|--------------------------------------------|---------------------|----------------------------------------------------------|
| `firmware_version()`                       | `str`               | FTP `SYST`; `PSINF` when the reply is garbled (FW 6A10)  |
| `info()`                                   | `DeviceInfo`        | the `PSINF` report                                       |
| `status()`                                 | `tuple[PortStatus]` | Telnet `monitor`, one entry per physical port            |
| `read_config()`                            | `DeviceConfig`      | the `CONFIG` file, typed                                 |
| `read_config_text()`                       | `str`               | the `CONFIG` file exactly as the device sends it         |
| `queue_state(queue, *, long_format=False)` | `str`               | LPD queue state of `L1` to `L8`, unparsed; no print data |

```python
from ipaddress import IPv4Address

from sercomm_printserver import PortState, PortType

assert server.firmware_version() == "6022"

info = server.info()
assert (info.server_name, info.default_name) == ("PS_EXAMPLE", "SC123456")
assert info.mac_address == "00:c0:02:12:34:56"  # derived from the default name
assert info.ip_address == IPv4Address("192.0.2.52")

config = server.read_config()
assert config.box_name == "PS_EXAMPLE"
assert [printer.port.value for printer in config.logical_printers] == ["P1", "P2", "SP"]
assert config.tcp_ip.dhcp is False

[p1, p2, sp] = server.status()
assert p1.state is PortState.IDLE and sp.type is PortType.SERIAL
```

`DeviceInfo` keeps every line of the report: the header entries in `general`, the sections (`TCP/IP
Info` and the like) in `sections`. `mac_address`, `ip_address`, `subnet_mask` and `gateway` are
`None` when the report does not carry them.

`DeviceConfig` is described under [Changing the configuration](#changing-the-configuration).

### PortStatus

One physical port as the `monitor` command reports it. An idle port reports only its first three
fields.

| Attribute        | Type               | Values                                                                                                  |
|------------------|--------------------|---------------------------------------------------------------------------------------------------------|
| `port`           | `PortId`           | `P1`, `P2`, `P3`, `SP`                                                                                  |
| `state`          | `PortState`        | `Idle`, `Printing`                                                                                      |
| `type`           | `PortType`         | `Parallel`, `Serial`, `USB`                                                                             |
| `printer_status` | `PrinterStatus`    | `On-Line`, `Offline`, `Out Of Paper`                                                                    |
| `bytes_serviced` | `int \| None`      | bytes of the current job; `None` on an idle port                                                        |
| `occupied_by`    | `str \| None`      | the protocol holding the port, as text                                                                  |
| `occupant`       | `Occupant \| None` | `occupied_by` as `Occupant.DIRECT_SOCKET` or `Occupant.LPD`; `None` for a free port or any other holder |

`Occupant` is imported from `sercomm_printserver.domain.port_status`. A port state, type or printer
status the firmware family does not print is refused with `DeviceResponseError` rather than guessed.

## Wedged ports

A RAW connection that lost its data leaves its port reading `Printing` / `Direct Socket` with 0
bytes serviced until the device restarts. An open connection, your own included, reads exactly the
same. `check()` tells them apart: for a port that reads that way it reads the configuration and makes
a bare connect, with no data, to every RAW port (`L1` to `L3`) routed there. A port a client holds
refuses the connect; a wedged one accepts it.

`check()` returns a `CheckResult` (from `sercomm_printserver.application.print_server`):

| Field       | Type                     | Meaning                                                    |
|-------------|--------------------------|------------------------------------------------------------|
| `ports`     | `tuple[PortHealth, ...]` | every port's health; after a restart, as read after it     |
| `wedged`    | `bool`                   | whether a port in `ports` is wedged                        |
| `restarted` | `bool`                   | whether `reset_if_wedged()` restarted the device           |
| `before`    | `tuple[PortHealth, ...]` | every port's health before that restart; empty without one |

`PortHealth` (from `sercomm_printserver.domain.port_health`) holds the port's `status`, its `verdict`
and `probed`, the RAW ports the probe connected to.

| `PortVerdict` | Meaning                                                                              |
|---------------|--------------------------------------------------------------------------------------|
| `IDLE`        | the port is idle                                                                     |
| `PRINTING`    | busy, and not in the state a wedge leaves                                            |
| `HELD`        | reads like a wedge, but a RAW port routed there refused the probe: a client holds it |
| `WEDGED`      | reads like a wedge, and every RAW port routed there accepted the probe               |
| `UNPROBED`    | reads like a wedge, but no RAW port is routed there, so nothing could decide it      |

`reset_if_wedged()` runs `check()`, and only when a port is wedged restarts the device, waits for it
and checks again. A restart interrupts every port, which is why it is not done for any other verdict.

```python
from sercomm_printserver.domain.port_health import PortVerdict

WEDGED = IDLE.replace(
    "(SP)STATE: Idle\nTYPE: Serial\nPRINTER STATUS: On-Line\n",
    "(SP)STATE: Printing\nTYPE: Serial\nPRINTER STATUS: On-Line\n"
    "BYTES SERVICED:          0\nOCCUPIED BY: Direct Socket\n",
)

device.monitor_text = WEDGED
found = server.check()
assert found.wedged and found.ports[2].verdict is PortVerdict.WEDGED
assert found.ports[2].probed == (9102,)  # L3, the printer routed to SP

device.raw_refusing = {9102}  # a client holds the port: the probe is refused
assert server.check().ports[2].verdict is PortVerdict.HELD

device.raw_refusing = set()
device.monitor_replies = [WEDGED, IDLE]  # wedged before the restart, idle after it
result = server.reset_if_wedged()
assert result.restarted and not result.wedged
assert result.before[2].verdict is PortVerdict.WEDGED
device.monitor_text = IDLE
```

`reset_if_wedged()` raises `DeviceUnavailableError` when the device does not come back from the
restart in time (see [Restart](#restart-password-factory-settings)).

Two states this check cannot see: a RAW port that refuses every connect while the monitor reads
`Idle`, and an idle port whose printer does not answer.

## Changing the configuration

A configuration change is a read-modify-write of the whole `CONFIG` file:

1. `read_config()` returns a `DeviceConfig`, a frozen pydantic model of every parameter the device
   reported.
2. `with_value(config, key, value)` returns a copy with one parameter set. `key` is the parameter's
   token (`BOX_NAME`, case-insensitive) or its four-digit line number; `value` is written as in a
   `CONFIG` file (`Enable`, `192.0.2.60`). The value is validated exactly as if the device had
   reported it, and a refused one raises `ConfigFormatError`. Editing the model with `model_copy`
   works as well.
3. `plan_config(new)` lists what writing `new` would change, without writing.
4. `write_config(new, *, apply=True)` uploads `new` if it differs, reads it back and compares.

```python
from sercomm_printserver import with_value

current = server.read_config()
renamed = with_value(current, "BOX_NAME", "PRINTER2")

[change] = server.plan_config(renamed)
assert (change.number, change.token, change.old, change.new) == (1, "BOX_NAME", "PS_EXAMPLE", "PRINTER2")

result = server.write_config(renamed, apply=False)
assert result.written and not result.applied
assert result.reachable_at == "192.0.2.52"
assert server.read_config().box_name == "PRINTER2"

assert server.write_config(renamed).written is False  # nothing differs, nothing is sent
```

`write_config` returns a `ConfigWriteResult`:

| Field          | Type                       | Meaning                                                                   |
|----------------|----------------------------|---------------------------------------------------------------------------|
| `changes`      | `tuple[ConfigChange, ...]` | the parameters that differ from what the device had                       |
| `written`      | `bool`                     | whether anything was uploaded                                             |
| `applied`      | `bool`                     | whether the device was restarted so the configuration takes effect        |
| `reachable_at` | `str \| None`              | the address the device answers on afterwards; `None` when DHCP chooses it |

With `apply=True` the device is restarted after the upload, and the call waits until it has
restarted and answers FTP again, at the new address when the configuration moves it. With DHCP on,
nothing waits, since the new address is unknown. The wait raises `DeviceUnavailableError` as
`reset()` does. A stored configuration takes effect only after a restart, so `apply=False` leaves
the device running on its old settings until the next `reset()`.

```python
moved = with_value(server.read_config(), "IP_ADDR", "192.0.2.60")
result = server.write_config(moved)
assert result.applied and result.reachable_at == "192.0.2.60"
```

The upload replaces the whole file, so always change the configuration you read rather than one
built from scratch. Nothing you did not touch gets lost: a parameter the package does not model is
kept verbatim in `DeviceConfig.unmodeled` and written back at its line, and for a file the device
produced `render_config(parse_config(text)) == text`.

When the device stored something other than what was sent, `write_config` raises
`DeviceResponseError` naming each parameter. A PS301 has done this rarely and stored the next upload
correctly, so call it again. There is no automatic retry, because it would hide a device that really
rewrites a value.

One parameter cannot be checked. The device reads the mail password (`4102 MAIL_PAS`) back as
asterisks, so `config.mail.password` holds the mask, and a configuration read and written back
uploads that mask. The library relies on the device keeping its stored value when it receives the
mask, and the read-back comparison skips this parameter. A new mail password set with
`with_value(config, "MAIL_PAS", ...)` is therefore written but not verified.

`parse_config(text)` and `render_config(config)` convert between `CONFIG` text and `DeviceConfig`
without a device; both raise `ConfigFormatError` on text or values outside the firmware family.

## Restart, password, factory settings

| Method                             | Effect                                                                         |
|------------------------------------|--------------------------------------------------------------------------------|
| `reset(*, wait=True)`              | restart the device; a stored configuration takes effect                        |
| `set_password(password)`           | set the login password, a `SecretStr` of at most 19 printable ASCII characters |
| `clear_password(*, confirm_name)`  | clear the login password                                                       |
| `store_ip(*, confirm_name)`        | store the address the device answers on now as its static IP                   |
| `factory_default(*, confirm_name)` | factory settings: no password, an empty name, IP 0.0.0.0 with DHCP on          |

`reset(wait=True)` returns once the device has restarted, which it proves by an SNMP uptime no longer
than the time since the restart was triggered, and answers FTP again. It raises
`DeviceUnavailableError` when that does not happen within 120 s, or when the device never answers
SNMP, so the restart cannot be confirmed. `reset(wait=False)` returns once the restart is triggered;
the device restarts about 5 s later.

The three actions that can cut a device off the network need the device's name as confirmation:
its server name or its default name, case-insensitive. Anything else raises
`ConfirmationRequiredError` before the device is touched. `factory_default` returns once the reset is
triggered; the device then takes an address by DHCP, and without a DHCP server it is reached with
the [ARP trick](#a-device-without-a-usable-address-the-arp-trick).

```python
from pydantic import SecretStr

from sercomm_printserver import ConfirmationRequiredError

server.set_password(SecretStr("s3cret"))
assert device.credential == "s3cret"

try:
    server.clear_password(confirm_name="some other name")
except ConfirmationRequiredError as error:
    print(error)  # clearing the password needs the device's name as confirmation (PS_EXAMPLE or SC123456)
assert device.credential == "s3cret"

server.clear_password(confirm_name="SC123456")
assert device.credential == ""
```

`set_password` raises `ValueError` for a password that is longer than 19 characters or not printable
ASCII.

## Printing

### PrintData

`PrintData` holds the bytes of one job and hands them out in pieces of at most 64 KiB, so a large
job never sits in memory whole. Every print method takes a `PrintData` or plain `bytes`.

| Constructor                                   | `size`                                                       | Readable                    |
|-----------------------------------------------|--------------------------------------------------------------|-----------------------------|
| `PrintData.of(data)`                          | `len(data)`                                                  | any number of times         |
| `PrintData.from_path(path)`                   | the file's size when built; `None` for a FIFO or device      | every send reopens the file |
| `PrintData.from_stream(stream, *, size=None)` | `size`, else what a regular file has left; `None` for a pipe | once                        |

- `from_path` reads the file's size when the data is built and its bytes when they are sent. It
  raises `OSError` (`FileNotFoundError` and the like) when the file cannot be examined.
- `from_stream` reads a binary stream (`sys.stdin.buffer`, an open file) from its current position to
  its end and never closes it. A second send of the same object raises `RuntimeError`; build a new
  `PrintData` instead.
- `bytes_read` counts the bytes the most recent send handed out, which gives a pipe's size after the
  send.
- In-memory data compares equal to `bytes` with the same content; file and stream data equal only
  themselves.

```python
import io
from pathlib import Path

from sercomm_printserver import PrintData

Path("/tmp/label.prn").write_bytes(b'N\nA50,50,0,4,1,1,N,"HELLO"\nP1\n')

assert PrintData.of(b"hello\f").size == 6
assert PrintData.from_path("/tmp/label.prn").size == 30

piped = PrintData.from_stream(io.BytesIO(b"from a pipe"))
assert piped.size is None  # an in-memory stream is not a regular file
assert server.print_raw(2, piped) == 11
assert piped.bytes_read == 11
try:
    server.print_raw(2, piped)
except RuntimeError as error:
    print(error)  # this print data reads a stream, which was already consumed; ...
```

### PrintJob

`PrintJob(*, data, name="job", user="sercomm", client_host="localhost")` is the data plus the names
LPD puts into the job's control file. `data` takes a `PrintData` or `bytes`; bytes are wrapped.
`name` is 1 to 99 printable ASCII characters without spaces, `user` and `client_host` 1 to 31. The
device prints the data as it arrives and ignores other control-file options, so no others are
carried.

### The three ways to print

| Method                                                       | Returns                   | Sends to                                                            |
|--------------------------------------------------------------|---------------------------|---------------------------------------------------------------------|
| `print_lpd(queue, job)`                                      | `int`, bytes of data sent | the LPD queue `queue`, `L1` to `L8`                                 |
| `print_raw(logical_printer, data)`                           | `int`, bytes sent         | the RAW port of logical printer 1 to 3                              |
| `print_raw_verified(logical_printer, data, *, timeout=30.0)` | `PortStatus`              | the same RAW port, waiting for the port to be idle before and after |

A RAW port belongs to a logical printer, not to a physical port: the data goes to whichever port the
printer is routed to (`Ln_PROUT`), as an LPD job would.

- `print_lpd` sends the data file before the control file. Data of unknown size (a pipe) is copied
  to a temporary file first, because LPD announces the size ahead of the data; `TMPDIR` chooses the
  directory.
- `print_raw` reads the configuration first. For a printer on the serial port it keeps the
  connection open until the job has crossed the serial link at the configured baud rate, plus
  0.25 s: closing earlier and opening the next RAW connection too soon wedges the port. A parallel or
  USB printer gets no wait. Empty data is refused before the device is contacted.
- `print_raw_verified` waits up to `timeout` for the routed port to read `Idle`, sends, and waits up
  to `timeout` again for it to read `Idle`. The worst case is twice `timeout`. A busy port accepts a
  new job without complaint, so this is the way to avoid stacking jobs behind a stuck one. `Idle`
  means the port is free, never that a page came out.

```python
from sercomm_printserver import PrintJob, PortBusyError, JobNotDrainedError

assert server.print_lpd("L1", PrintJob(data=b"hello\r\n\f", name="greeting")) == 8
assert server.print_raw(1, PrintData.from_path("/tmp/label.prn")) == 30

after = server.print_raw_verified(3, b"N\nP1\n")
assert after.port.value == "SP" and after.state is PortState.IDLE

BUSY = IDLE.replace(
    "(P1)STATE: Idle\nTYPE: Parallel\nPRINTER STATUS: On-Line\n",
    "(P1)STATE: Printing\nTYPE: Parallel\nPRINTER STATUS: On-Line\nBYTES SERVICED:       1024\nOCCUPIED BY: LPD\n",
)
device.monitor_text = BUSY
sends = len(device.raw_sends)
try:
    server.print_raw_verified(1, b"N\nP1\n", timeout=0.0)
except PortBusyError as error:
    print(error)  # 192.0.2.52: nothing was sent, P1 is still Printing after 0 s (occupied by LPD, ...)
assert len(device.raw_sends) == sends  # safe to try again later

device.monitor_replies = [IDLE]  # idle before the send, busy after it
try:
    server.print_raw_verified(1, b"N\nP1\n", timeout=0.0)
except JobNotDrainedError as error:
    print(error)  # 192.0.2.52: the data was sent, but P1 is still Printing 0 s later (...)
assert len(device.raw_sends) == sends + 1  # the job is on its way: do not resend it
device.monitor_text = IDLE
```

### When a print fails: was it sent?

This device prints data as it arrives, so a failure after the first byte can leave part of the job
on paper. Resend only where this table says nothing was sent.

| Exception                  | From                              | Sent?                                                                                                                                    |
|----------------------------|-----------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| `ValueError`               | all three                         | no: empty data, a bad queue name, or a printer without a RAW port                                                                        |
| `SpoolError`               | `print_lpd`                       | no: the temporary file for data of unknown size failed                                                                                   |
| `PortBusyError`            | `print_raw_verified`              | no: the port stayed busy for `timeout` before the send                                                                                   |
| `DeviceUnavailableError`   | `print_lpd`                       | no: the device did not answer before any data                                                                                            |
| `DeviceUnavailableError`   | `print_raw`, `print_raw_verified` | no: the device could not be reached, or the connection broke before it took any byte                                                     |
| `DeliveryUnconfirmedError` | `print_raw`, `print_raw_verified` | yes, at least partly: the connection broke after the device took data; the message says how many bytes were sent                         |
| `DeviceResponseError`      | `print_lpd`                       | maybe: the device refused a step or broke off the exchange                                                                               |
| `DeviceResponseError`      | `print_raw`, `print_raw_verified` | no: the configuration routes the printer to `SP` but has no serial settings, or (verified print only) to a port the status does not list |
| `PrintSourceChangedError`  | `print_lpd`                       | maybe: the file grew or shrank while it was sent; the job was left unterminated, but part of it may be on paper                          |
| `JobNotDrainedError`       | `print_raw_verified`              | yes: the port stayed busy, or could not be read, after the send                                                                          |
| `OSError`, `RuntimeError`  | all three                         | maybe: reading the file or stream failed, or a stream was already read                                                                   |

`print_raw` and `print_raw_verified` also read the configuration first, so the
[reading errors](#exceptions) apply to them before anything is sent.

## Discovery

`discover_print_servers(*, networks=None, timeout=3.0)` finds the family's print servers by their FTP
greeting (`220 Print Server Ready.`). It never logs in and never touches a print port.

- `networks` is a list of IPv4 CIDR strings (`"192.0.2.0/24"`). `None` searches the networks this
  host is attached to, up to 4096 addresses in all; the networks left out are listed in `skipped`.
- Named networks are never cut short: more than 4096 addresses in them raises `ValueError`, as does a
  string that is not an IPv4 network.

It returns a `DiscoveryReport` with `networks`, `probed` (the number of addresses tried), `skipped`
and `devices`, a tuple of `DiscoveredDevice(host, mac_address)` ordered by address. The MAC comes
from this host's neighbour cache and is `None` when the cache does not know it.

```python
# needs a real network
from sercomm_printserver import discover_print_servers

for found in discover_print_servers(networks=["192.0.2.0/24"]).devices:
    print(found.host, found.mac_address)
```

## A device without a usable address: the ARP trick

A device whose address is unknown, or outside this host's subnet (after a factory reset without a
DHCP server it is 0.0.0.0), can still be reached by its MAC: this host maps a free address of its
own subnet to the device's MAC with a static ARP entry, and the device answers packets sent there.
The module `arp_trick` does that and removes the entry again in every case.

| Function                                                                          | Does                                                                                  |
|-----------------------------------------------------------------------------------|---------------------------------------------------------------------------------------|
| `reach(table, open_server, *, endpoint, ip, mac)`                                 | reads the device's `PSINF` over the borrowed address; changes nothing                 |
| `assign_ip(table, open_server, *, endpoint, ip, mac, netmask=None, gateway=None)` | stores `ip` as the device's static address and restarts it there                      |
| `factory_reset(table, open_server, *, endpoint, ip, mac, confirm_name)`           | restores factory settings; `confirm_name` must be the default name derived from `mac` |
| `borrowed_address(table, *, ip, mac)`                                             | context manager that holds the static entry for a block                               |

- `table` is this host's neighbour table: `IpscoutNeighborTable(*, interface=None)`. Writing it
  needs root or `CAP_NET_ADMIN` on Linux, root on macOS, Administrator on Windows.
- `open_server` turns an endpoint into a `PrintServer`; pass `open_print_server`.
- `endpoint` carries the login, password and timeouts; its host is replaced by `ip`.
- `mac` takes any common spelling (colons, dashes, none, Cisco dots); `normalise_mac(mac)` gives the
  form the package uses, `00:c0:02:12:34:56`.

Before it borrows `ip` the trick asks who holds it, and refuses (`ValueError`) when another MAC does.
It also refuses with `UnverifiedAddressError` when this host could not send an ARP request and its
cache does not know the address, because then nothing shows the address is free. Each function
returns an `ArpResult` with `mac_address`, `borrowed_ip`, `device` (the `DeviceInfo` read) and, for
`assign_ip`, `write` (the `ConfigWriteResult`). The device at the borrowed address must call itself
by the default name its MAC gives, or `ConfirmationRequiredError` is raised.

```python
from ipaddress import IPv4Address

from sercomm_printserver import arp_trick, normalise_mac
from sercomm_printserver.adapters.memory.neighbors import FakeNeighborTable

table = FakeNeighborTable()  # IpscoutNeighborTable() on a real host
found = arp_trick.reach(
    table,
    lambda endpoint: server,  # open_print_server on a real host
    endpoint=DeviceEndpoint(host="192.0.2.77"),  # login and timeouts; the host is replaced by ip
    ip=IPv4Address("192.0.2.77"),
    mac="00-C0-02-12-34-56",
)
assert found.device.default_name == "SC123456"
assert found.mac_address == normalise_mac("00c0.0212.3456")
assert table.entries == {}  # the static entry is gone again
```

`HostPrivilegeError` and `NeighborTableError` come from writing or removing the ARP entry.
`assign_ip` raises `ConfigFormatError` for firmware 6A10, which has no DHCP switch, so its address
cannot be made static.

## Exceptions

Every failure is one of these, exported from `sercomm_printserver`, or a plain `ValueError` for an
argument the call refuses before it starts. Most derive from `OSError`, so catch the specific class
first: an `except OSError` takes them all.

| Exception                     | Base              | Raised when                                                                                                |
|-------------------------------|-------------------|------------------------------------------------------------------------------------------------------------|
| `DeviceUnavailableError`      | `ConnectionError` | the device could not be reached: refused, timed out, no route, or a connection broke before any print data |
| `DeliveryUnconfirmedError`    | `ConnectionError` | `print_raw`: the connection broke after the device took print data; not a `DeviceUnavailableError`         |
| `DeviceResponseError`         | `ValueError`      | the device answered, but not in the form this firmware family uses; or it stored a different configuration |
| `AuthenticationRequiredError` | `PermissionError` | the device wants a login and password the endpoint does not have (FTP 530)                                 |
| `ConfigFormatError`           | `ValueError`      | `CONFIG` text or a value is not one the family uses; names the parameter                                   |
| `ConfirmationRequiredError`   | `PermissionError` | a destructive action without the device's name; nothing was done                                           |
| `PortBusyError`               | `TimeoutError`    | `print_raw_verified`: the port stayed busy before the send; nothing was sent                               |
| `JobNotDrainedError`          | `TimeoutError`    | `print_raw_verified`: the job was sent, but the port did not read idle in time                             |
| `PrintSourceChangedError`     | `OSError`         | `print_lpd`: the file changed size while it was sent; part may be on paper                                 |
| `SpoolError`                  | `OSError`         | `print_lpd`: data of unknown size could not be copied to a temporary file; nothing was sent                |
| `HostPrivilegeError`          | `PermissionError` | ARP trick: this host may not change its neighbour table                                                    |
| `UnverifiedAddressError`      | `PermissionError` | ARP trick: nothing shows the address to borrow is free                                                     |
| `NeighborTableError`          | `OSError`         | ARP trick: the neighbour table could not be read or written for another reason                             |
| `ConfigurationError`          | `Exception`       | the command line tool's own settings are missing or invalid; no `PrintServer` method raises it             |

Reading methods (`info`, `status`, `read_config` and the rest) raise `DeviceUnavailableError`,
`DeviceResponseError`, `AuthenticationRequiredError` and, for the configuration,
`ConfigFormatError`. Every FTP read, upload and action is retried once with the device's name as
login after a 530 when `DeviceEndpoint.login` is empty, and raises `AuthenticationRequiredError`
when that is refused too.

## Testing your code against the in-memory fakes

The fakes the package tests itself with are importable, so your own code can be tested end to end
without a network. They live under `sercomm_printserver.adapters.memory` and are not part of the
top-level `__all__`.

- `FakeDevice(*, config, psinf, monitor, firmware="6022", login_for_writes=None, clock=time.monotonic)`
  from `.device` stands behind every protocol port at once: it serves `config` and `psinf`, answers
  `monitor` with the given text, stores an uploaded `CONFIG` verbatim, masks `MAIL_PAS` on read, and
  simulates a restart for the SNMP uptime. `FakeTftp(device)` is its TFTP side.
- `FakeNeighborTable(entries=None, *, method=LookupMethod.ACTIVE)` from `.neighbors` is a neighbour
  table held in a dict.

Wire them into a `PrintServer` through `DevicePorts` (from `sercomm_printserver.application.print_server`),
as in [the setup above](#the-examples-on-this-page-run-against-a-fake-device). `PrintServer` also
takes `sleep` and `clock`, so restart and print waits do not wait in a test.

What a `FakeDevice` records, and what a test can set:

| Attribute                 | Meaning                                                                                             |
|---------------------------|-----------------------------------------------------------------------------------------------------|
| `config`, `psinf`         | the files it serves; an upload replaces `config`                                                    |
| `monitor_text`            | what `monitor` prints                                                                               |
| `monitor_replies`         | answers to the next `monitor` calls, oldest first; a `DeviceUnavailableError` in the list is raised |
| `lpd_jobs`                | `(queue, PrintJob)` per LPD job, data read into memory                                              |
| `raw_sends`, `raw_drains` | `(port, bytes)` per RAW send, and the serial-link wait each was given                               |
| `raw_probes`              | RAW ports a wedge probe connected to                                                                |
| `raw_refusing`            | RAW ports that refuse a probe, as one a client holds does                                           |
| `actions`                 | restart, factory default, password reset and store-IP actions, in order                             |
| `credential`              | the stored login password                                                                           |
| `reachable`               | set to `False` and every call raises `DeviceUnavailableError`                                       |
| `login_for_writes`        | when set, uploads and actions need this login and `credential`                                      |
| `store_rewrites`          | uploaded text mapped to the text actually stored, to provoke a failed write                         |

```python
from sercomm_printserver import DeviceUnavailableError


def print_label(server: PrintServer, text: str) -> int:
    """The code under test: one label on L1."""
    return server.print_raw(1, f'N\nA50,50,0,4,1,1,N,"{text}"\nP1\n'.encode("ascii"))


assert print_label(server, "HELLO") == 30
assert device.raw_sends[-1] == (9100, b'N\nA50,50,0,4,1,1,N,"HELLO"\nP1\n')

device.reachable = False
try:
    print_label(server, "HELLO")
except DeviceUnavailableError as error:
    print(error)  # 192.0.2.52 does not answer
device.reachable = True
```

## Application configuration

`get_config(*, profile=None, start_dir=None, dotenv_path=None)` loads the command line tool's layered
configuration (defaults, app, host, user, `.env`, environment), including the `[device]` section the
CLI builds its endpoint from. A library caller does not need it: build the `DeviceEndpoint` yourself.
[CONFIG.md](../CONFIG.md) lists the keys. `print_info()` prints the package metadata.
