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


`sercomm-printserver` will be a command-line tool and Python library for the SerComm family of
network print servers: the SerComm PS301 and its OEM variants sold by TRENDnet, Linksys,
Netgear, Perle and others, with two parallel ports plus one serial port or a single parallel
port. They are configured over FTP through virtual files (`CONFIG`, `PSINF`, `RESET`) and
print over LPD and raw sockets. What is known about the devices so far is in
[docs/Manual-PS301.md](docs/Manual-PS301.md) (German).

Status: work in progress. The print-server client is not written yet; the CLI so far has the
`info` and configuration commands it inherited from the bitranox CLI template, and the
configuration already carries a `[device]` section for the print server it will talk to.

It builds on:
- CLI entry point styled with rich-click (rich output + click ergonomics).
- Layered configuration system with lib_layered_config (defaults -> app -> host -> user -> .env -> env).
  The `.env` is the first one found from the current directory upward; when there is none,
  `$XDG_CONFIG_HOME/sercomm-printserver/.env` (`~/.config/...` when unset) is read on Linux
  (see [CONFIG.md](CONFIG.md) for macOS and Windows).
- Rich structured logging with lib_log_rich (console, journald, eventlog, Graylog/GELF).
- Exit-code and messaging helpers powered by lib_cli_exit_tools.
- Metadata helpers ready for packaging, testing, and release automation.


### Python 3.10+ Baseline

- The project targets **Python 3.10 and newer**.
- Runtime dependencies are declared with >= floors in pyproject.toml. Dev
  dependencies (pytest, ruff, pyright, bandit, etc.) are declared the same way.
- CI workflows exercise GitHub's rolling runner images (`ubuntu-latest`,
  `macos-latest`, `windows-latest`) and cover CPython 3.10 through 3.15
  alongside the latest available 3.x release provided by Actions.

---

## Install - recommended via uv

[uv](https://docs.astral.sh/uv/) is an ultrafast Python package manager written in Rust (10-20x faster than pip/poetry).

### Install uv (if not already installed) 
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Copy the actual binaries
cp /root/.local/bin/uv /usr/local/bin/uv
cp /root/.local/bin/uvx /usr/local/bin/uvx

# Ensure world-executable
chmod 755 /usr/local/bin/uv /usr/local/bin/uvx

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
uv tool install --exclude-newer "7 days" sercomm_printserver
git clone https://github.com/bitranox/sercomm-printserver.git && cd sercomm-printserver && uv sync --locked && uv run sercomm_printserver --help
```

If you depend on sercomm_printserver in your own project, give that project the same cooldown (7 days here, as
an example) and commit the `uv.lock` that `uv add sercomm_printserver` writes:

```toml
[tool.uv]
exclude-newer = "7 days"
```

---

## Configuration

See [CONFIG.md](CONFIG.md) for detailed documentation on the layered configuration system, including precedence rules, profile support, and customization best practices.

---

## Quick Start

```bash
# Install
uv tool install sercomm_printserver

# Verify
sercomm-printserver --version

# deploy config files (user level; --target app or host needs sudo)
sercomm-printserver config-deploy --target user

# Try it out
sercomm-printserver info
sercomm-printserver config
```

---

## Usage

The CLI leverages [rich-click](https://github.com/ewels/rich-click) so help output, validation errors, and prompts render with Rich styling while keeping the familiar click ergonomics.

### Available Commands

```bash
# Display package information
sercomm-printserver info

# Configuration management
sercomm-printserver config                         # Show current configuration
sercomm-printserver config --format json           # Show as JSON
sercomm-printserver config --section lib_log_rich  # Show specific section
sercomm-printserver config --profile production    # Use a named profile

# Deploy configuration templates to target directories
# Without profile:
sercomm-printserver config-deploy --target app    # -> /etc/xdg/{slug}/config.toml
sercomm-printserver config-deploy --target host   # -> /etc/xdg/{slug}/hosts/{hostname}.toml
sercomm-printserver config-deploy --target user   # -> ~/.config/{slug}/config.toml

# With profile:
sercomm-printserver config-deploy --target app --profile production   # -> /etc/xdg/{slug}/profile/production/config.toml
sercomm-printserver config-deploy --target host --profile production  # -> /etc/xdg/{slug}/profile/production/hosts/{hostname}.toml
sercomm-printserver config-deploy --target user --profile production  # -> ~/.config/{slug}/profile/production/config.toml

# With custom permissions (POSIX only):
sercomm-printserver config-deploy --target user --file-mode 640       # Files with rw-r----- (640)
sercomm-printserver config-deploy --target user --dir-mode 750        # Directories with rwxr-x--- (750)
sercomm-printserver config-deploy --target app --no-permissions       # Skip permission setting (use umask)

# Profile names: alphanumeric, hyphens, underscores; max 64 chars; must start with letter/digit
# See CONFIG.md for full validation rules

# Deploy configuration examples
sercomm-printserver config-generate-examples --destination ./examples

# Load configuration from an explicit .env file (skips upward directory search)
sercomm-printserver --env-file /path/to/.env config
sercomm-printserver --env-file ./environments/production.env config --section device

# Override configuration at runtime (repeatable --set)
sercomm-printserver --set lib_log_rich.console_level=DEBUG config
sercomm-printserver --set device.host=192.0.2.52 config --section device

# Show a full traceback when a command fails unexpectedly
sercomm-printserver --traceback config

# All commands work with any entry point
python -m sercomm_printserver info
uvx sercomm_printserver info
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
