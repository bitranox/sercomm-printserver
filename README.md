# sercomm-printserver

<!-- Badges -->
[![CI](https://github.com/bitranox/sercomm-printserver/actions/workflows/default_cicd_public.yml/badge.svg)](https://github.com/bitranox/sercomm-printserver/actions/workflows/default_cicd_public.yml)
[![CodeQL](https://github.com/bitranox/sercomm-printserver/actions/workflows/codeql.yml/badge.svg)](https://github.com/bitranox/sercomm-printserver/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Open in Codespaces](https://img.shields.io/badge/Codespaces-Open-blue?logo=github&logoColor=white&style=flat-square)](https://codespaces.new/bitranox/sercomm-printserver?quickstart=1)
[![PyPI](https://img.shields.io/pypi/v/sercomm-printserver.svg)](https://pypi.org/project/sercomm-printserver/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/sercomm-printserver.svg)](https://pypi.org/project/sercomm-printserver/)
[![Code Style: Ruff](https://img.shields.io/badge/Code%20Style-Ruff-46A3FF?logo=ruff&labelColor=000)](https://docs.astral.sh/ruff/)
[![codecov](https://codecov.io/gh/bitranox/sercomm-printserver/graph/badge.svg)](https://codecov.io/gh/bitranox/sercomm-printserver)
[![security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)


`sercomm-printserver` is a command-line tool and Python library for the SerComm family of
network print servers: the SerComm PS301 and the same hardware sold by TRENDnet, Perle, Netgear
and Linksys (one to three parallel ports, on some models a serial or USB port). It finds
them on the network, reads their status and configuration, changes settings, restarts them,
prints to them over LPD or raw sockets, and recovers a device whose address or password is
lost.

These devices are managed over FTP through "virtual files", and some of those files are actions:
reading `RESET` restarts the device, reading `DEFAULTC` wipes its settings. The tool never touches
them by accident. Anything that changes the device needs `--yes`, and `device-config set` /
`import` show the changes first. `factory-default`, `password clear`, `store-ip` and
`arp factory-reset` also need the device's name (`--confirm-name`). Every device command can
answer in JSON, so scripts get the same information people do.

What is known about the devices, models and firmware versions is in
[docs/Manual-PS301.md](docs/Manual-PS301.md) (German) and
[docs/config-keys.md](docs/config-keys.md).

The CLI is built on rich-click, `lib_layered_config` (defaults, app, host and user files, `.env`
and environment), `lib_log_rich` and `lib_cli_exit_tools`. Static ARP entries for the address
recovery are written natively through [ipscout](https://github.com/bitranox/ipscout).

### Python 3.10+ Baseline

- The project targets **Python 3.10 and newer**.
- Runtime dependencies are declared with >= floors in pyproject.toml. Dev
  dependencies (pytest, ruff, pyright, bandit, etc.) are declared the same way.
- CI tests CPython 3.10 through 3.15 (taken from the pyproject classifiers) on
  `ubuntu-latest` and `windows-latest`, and the newest of them on `macos-latest`.

---

## Install - recommended via uv

[uv](https://docs.astral.sh/uv/) is an ultrafast Python package manager written in Rust (10-20x faster than pip/poetry).

### Install uv (if not already installed) 
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### One-shot run (no install needed)

```bash
uvx sercomm_printserver@latest --help
```

### Persistent install as CLI tool

```bash
# One-time install from PyPI (isolated environment, added to PATH)
uv tool install sercomm-printserver
# or from the git repository
uv tool install --from "git+https://github.com/bitranox/sercomm-printserver.git" sercomm-printserver
# Pick the interpreter explicitly if needed, e.g. --python 3.14
# Update (requires network)
uv tool upgrade sercomm-printserver
# Run
sercomm-printserver --help
```

### Install as project dependency

```bash
uv venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
uv pip install sercomm_printserver
```

For alternative install paths (pip, pipx, source builds, etc.), see
[INSTALL.md](INSTALL.md). All supported methods register both the
`sercomm_printserver` and `sercomm-printserver` commands on your PATH.

### Why we recommend uv: supply-chain protection

This repository commits a `uv.lock`. It pins every package the project needs, transitive
dependencies included, to an exact version and to the hashes of that version's files. The
`exclude-newer` setting under `[tool.uv]` in `pyproject.toml` adds a cooldown: uv leaves any
release younger than that out of the lock. CI installs from the lock, so a hijacked release that
gets pulled again within the cooldown never reaches our builds, and a file whose hash does not
match is refused.

That protection stays in this repository. The installable package declares only lower bounds
(`>=`) for its dependencies, so a plain `pip install` takes the newest release of every transitive
dependency at the moment you run it. If one of them was hijacked an hour earlier, you get the
hijacked version. `pipx install` and `uv tool install` without options do the same.

To install the command line tool with a cooldown of your own (uv then skips any release younger
than 7 days, transitive ones included), or to run the exact tree our CI tests:

```bash
uv tool install --exclude-newer "7 days" \
  --exclude-newer-package sercomm-printserver=false \
  --exclude-newer-package ipscout=false \
  --exclude-newer-package lib-log-rich=false \
  --exclude-newer-package lib-layered-config=false \
  --exclude-newer-package lib-cli-exit-tools=false \
  sercomm-printserver
git clone https://github.com/bitranox/sercomm-printserver.git && cd sercomm-printserver && uv sync --locked && uv run sercomm_printserver --help
```

If you depend on sercomm_printserver in your own project, give that project the same cooldown (7 days here, as
an example) and commit the `uv.lock` that `uv add sercomm_printserver` writes:

```toml
[tool.uv]
exclude-newer = "7 days"
exclude-newer-package = {sercomm-printserver = false, ipscout = false, lib-log-rich = false, lib-layered-config = false, lib-cli-exit-tools = false}
```

The exemptions cover this package and the libraries it shares an author and a release process
with. Without them, a cooldown leaves out every release of this tool for its first week, and a
release whose floor names a young library version cannot be installed at all (uv answers "No
solution found"). Every other dependency keeps the cooldown.

---

## Configuration

See [CONFIG.md](CONFIG.md) for detailed documentation on the layered configuration system, including precedence rules, profile support, and customization best practices.

---

## Quick Start

```bash
uv tool install sercomm-printserver

sercomm-printserver discover                         # find print servers on this host's networks
sercomm-printserver device-info --host 192.0.2.52    # name, MAC, firmware, addresses
sercomm-printserver status --host 192.0.2.52         # each port and its printer
sercomm-printserver print lpd L1 page.prn --host 192.0.2.52
```

---

## Usage

Run `sercomm-printserver <command> --help` for every option.

### Finding and reading devices

```bash
sercomm-printserver discover [--network 192.0.2.0/24]   # reads the FTP greeting only, never logs in
sercomm-printserver device-info                         # PSINF: names, MAC, firmware, addresses
sercomm-printserver firmware                            # firmware version, no login needed
sercomm-printserver status                              # port state and printer status
sercomm-printserver queue L1 [--long]                   # LPD queue state; sends no print data
```

Without `--network`, `discover` searches this host's networks up to 4096 addresses in all and
lists the networks beyond that budget under `skipped`; a named `--network` larger than 4096
addresses is refused (exit 22). `--timeout` is the wait for each host's greeting (default 3 s).

### Configuration of the device

```bash
sercomm-printserver device-config show                  # the whole CONFIG, typed
sercomm-printserver device-config get IP_ADDR           # one value, by token or line number
sercomm-printserver device-config set DHCP_MODE=Disable IP_ADDR=192.0.2.60          # shows the diff
sercomm-printserver device-config set DHCP_MODE=Disable IP_ADDR=192.0.2.60 --yes    # writes it
sercomm-printserver device-config export backup.cfg
sercomm-printserver device-config import backup.cfg --yes
```

A write restarts the device and waits until it answers again, at its new address when the
change moved it. The wait reads the device's SNMP uptime (community `public`): a device whose
SNMP agent does not answer fails after 120 s with exit 69, even though the change was applied.
`--no-apply` stores the change without the restart; it takes effect at the next `reset --yes`.
`reset --no-wait` returns without waiting.

### Restart, password, factory settings

```bash
sercomm-printserver reset --yes
sercomm-printserver password set --yes                  # hidden prompt, or --from-file FILE
sercomm-printserver password clear --yes --confirm-name PS_EXAMPLE
sercomm-printserver store-ip --yes --confirm-name PS_EXAMPLE
sercomm-printserver factory-default --yes --confirm-name PS_EXAMPLE
```

After `factory-default` the device restarts with its stored address set to 0.0.0.0, DHCP
switched on and its name empty. It answers wherever a DHCP server puts it (measured: the old
address again, so the address alone does not show the reset happened). Without a DHCP server it
has no usable address: bring it back with `arp assign-ip`. Its login is then the default name
`SC` plus the last six hex digits of its MAC, and `--confirm-name` takes only that name. Export
its configuration first (`device-config export`) if you want to restore it afterwards.

A password does not protect these devices: the firmware lets anyone on the network clear it
without logging in. Keep them on a network you trust.

### Printing

```bash
sercomm-printserver print lpd L1 page.prn               # LPD queue L1..L8
cat page.prn | sercomm-printserver print lpd L2 -
sercomm-printserver print raw 1 page.prn                # RAW port of logical printer 1
```

Only L1..L3 have a RAW port, and RAW data goes wherever that logical printer is routed, just like
an LPD job. Data that no printer takes stays queued and keeps the port busy until a restart
(`reset --yes`), so never send a test job, LPD or RAW, to a port without a printer. An LPD job
there fails after `--timeout` with exit 76, because the device holds back its acknowledgement.
`print lpd` names the job `job` unless `--job-name` says otherwise.

### A device without a usable address

The device answers any address this host maps to its MAC, which is how the vendor manuals
configure a new unit ("ARP trick"). `arp` borrows a free address in this host's subnet for the
call and removes the ARP entry afterwards. It needs root on Linux (or both `CAP_NET_ADMIN`, to
write the ARP entry, and `CAP_NET_RAW`, to check by an ARP request that the address is free), root
on macOS, or Administrator on Windows. An address another machine holds, or one this host cannot
check, is refused before anything is written (exit 22 and 13). `--interface` picks the network
interface; `assign-ip` keeps the device's netmask and gateway unless `--netmask` / `--gateway`
are given, and always switches DHCP off.

```bash
sudo sercomm-printserver arp reach --mac 00:c0:02:12:34:56 --ip 192.0.2.77
sudo sercomm-printserver arp assign-ip --mac 00:c0:02:12:34:56 --ip 192.0.2.77 --yes
sudo sercomm-printserver arp factory-reset --mac 00:c0:02:12:34:56 --ip 192.0.2.77 --yes --confirm-name SC123456
```

### JSON and exit codes

Every device command takes `--json` (indented) or `--json-bare` (one line). stdout then carries
only the envelope; anything meant for a person goes to stderr. Success and failure look like this:

```json
{"ok":true,"command":"firmware","data":{"host":"192.0.2.52","firmware":"6022"},"skipped":[]}
{"ok":false,"command":"firmware","error":"ConfigurationError","message":"no device given: pass --host or set [device] host in the configuration"}
```

A usage error (an unknown option, `print raw 4`) is reported by the command-line parser before
any JSON is written: exit 2 and a usage message on stderr. Exit codes do not depend on the format.

| Exit code | Meaning                                                                      |
|-----------|------------------------------------------------------------------------------|
| 0         | done                                                                         |
| 1         | any other failure, such as an ARP table this host could not change           |
| 2         | usage error: a missing or invalid option or argument                         |
| 13        | this host lacks a right (`arp`: the ARP table or sending an ARP request;     |
|           | `config-deploy`: a system dir)                                               |
| 22        | invalid argument                                                             |
| 69        | the device did not answer, or did not come back after a restart              |
| 76        | the device answered something this firmware family does not send, or stored  |
|           | a value other than the one sent (rare: run the command again)                |
| 77        | refused: confirmation missing, the device wants a login, or a wrong password |
| 78        | configuration error, such as no device address                               |

### Python

```python
from sercomm_printserver import DeviceEndpoint, PrintJob, open_print_server

server = open_print_server(DeviceEndpoint(host="192.0.2.52"))
server.print_lpd("L1", PrintJob(data=b"hello\r\n\f", name="greeting"))
print(server.info().firmware_version)
```

`discover_print_servers()`, `PrintServer.read_config()`, `write_config()` and `reset()`, and
`arp_trick` with `IpscoutNeighborTable` cover the rest.

### Application configuration

```bash
sercomm-printserver config                         # the merged configuration
sercomm-printserver config --section device
sercomm-printserver config-deploy --target user    # -> ~/.config/sercomm-printserver/config.toml
sercomm-printserver --set device.host=192.0.2.52 status
sercomm-printserver config-generate-examples --destination ./examples   # one placeholder file per layer
sercomm-printserver info                           # package metadata (name, version, ...)
```

See [CONFIG.md](CONFIG.md) for the precedence, profiles and every key.

### Claude Code skill

The repository is also a Claude Code plugin with a skill for operating these devices:

```text
/plugin marketplace add bitranox/sercomm-printserver
/plugin install sercomm-printserver@sercomm-printserver
```

---

### Device Settings

The `[device]` section names the print server the CLI will talk to. It ships empty; set it in
a configuration file, a `.env` file or the environment:

```toml
[device]
host = "192.0.2.52"     # IPv4 address or host name of the print server
login = ""              # FTP login; empty means "ask the device for its name"
password = ""           # FTP password; redacted in `config` output
timeout = 10.0          # seconds per network operation
raw_port_base = 9100    # RAW (direct socket) port of logical printer L1
```

```bash
export SERCOMM_PRINTSERVER___DEVICE__HOST=192.0.2.52
sercomm-printserver config --section device
```

See [CONFIG.md](CONFIG.md) for every key and its environment variable.

## Further Documentation

- [Install Guide](INSTALL.md)
- [Development Handbook](DEVELOPMENT.md)
- [Contributor Guide](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [Module Reference](docs/systemdesign/module_reference.md)
- [License](LICENSE)
