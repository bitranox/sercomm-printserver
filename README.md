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

Status: early. The code base is still the bitranox CLI template it was created from; the
print-server client is not written yet.

The template provides:
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
sercomm-printserver hello
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

# Greeting and error-handling demos
sercomm-printserver hello
sercomm-printserver fail
sercomm-printserver --traceback fail

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
sercomm-printserver --env-file ./environments/production.env send-notification ...

# Override configuration at runtime (repeatable --set)
sercomm-printserver --set lib_log_rich.console_level=DEBUG config
sercomm-printserver --set email.smtp_hosts='["smtp.example.com:587"]' config --format json

# Logging demo
sercomm-printserver logdemo
LOG_CONSOLE_LEVEL=DEBUG sercomm-printserver logdemo   # logdemo reads LOG_* only, not --set

# Send email
sercomm-printserver send-email \
    --to recipient@example.com \
    --subject "Test Email" \
    --body "Hello from bitranox!"

# Send email with HTML body and attachments
sercomm-printserver send-email \
    --to recipient@example.com \
    --subject "Monthly Report" \
    --body "See attached." \
    --body-html "<h1>Report</h1><p>Details in the PDF.</p>" \
    --attachment report.pdf

# Send plain-text notification
sercomm-printserver send-notification \
    --to ops@example.com \
    --subject "Deploy OK" \
    --message "Application deployed successfully"

# All commands work with any entry point
python -m sercomm_printserver info
uvx sercomm_printserver info
```

---

### Email Sending

The application includes email sending capabilities via [btx-lib-mail](https://pypi.org/project/btx-lib-mail/), supporting both simple notifications and rich HTML emails with attachments.

#### Email Configuration

Configure email settings via environment variables, `.env` file, or configuration files:

**Environment Variables:**

Environment variables use the format: `<PREFIX>___<SECTION>__<KEY>=value`
- Triple underscore (`___`) separates PREFIX from SECTION
- Double underscore (`__`) separates SECTION from KEY

```bash
# A list is a JSON array; a comma-separated value would be ONE host string
export SERCOMM_PRINTSERVER___EMAIL__SMTP_HOSTS='["smtp.gmail.com:587","smtp.backup.com:587"]'
export SERCOMM_PRINTSERVER___EMAIL__FROM_ADDRESS="alerts@myapp.com"
export SERCOMM_PRINTSERVER___EMAIL__SMTP_USERNAME="your-email@gmail.com"
export SERCOMM_PRINTSERVER___EMAIL__SMTP_PASSWORD="your-app-password"
export SERCOMM_PRINTSERVER___EMAIL__USE_STARTTLS="true"
export SERCOMM_PRINTSERVER___EMAIL__TIMEOUT="60.0"
```

**Configuration File**:
```toml
[email]
smtp_hosts = ["smtp.gmail.com:587", "smtp.backup.com:587"]  # Fallback to backup if primary fails
from_address = "alerts@myapp.com"
smtp_username = "myuser@gmail.com"
smtp_password = "secret_password"  # Consider using environment variables for sensitive data
use_starttls = true
starttls_verify = true   # false accepts any certificate: only for a known internal relay
timeout = 60.0
# local_hostname = "mail.example.com"   # EHLO name; set it where reverse DNS is slow
# delivery_deadline = 300               # upper bound in seconds for one SMTP session; 0 = none
```

A key `[email]` or `[email.attachments]` does not know is refused (exit 78,
`email.<key>: unknown key`), whichever layer it comes from, so a typo cannot leave a setting at
its default.

**`.env` File** (no prefix in .env; a prefixed key is not recognised):
```bash
# Email configuration for local testing
EMAIL__SMTP_HOSTS=["smtp.gmail.com:587"]
EMAIL__FROM_ADDRESS=noreply@example.com
```

#### Gmail Configuration Example

For Gmail, create an [App Password](https://support.google.com/accounts/answer/185833) instead of using your account password.
In a `.env` file (no prefix in .env; a prefixed key is not recognised):

```bash
EMAIL__SMTP_HOSTS=["smtp.gmail.com:587"]
EMAIL__FROM_ADDRESS=your-email@gmail.com
EMAIL__SMTP_USERNAME=your-email@gmail.com
EMAIL__SMTP_PASSWORD=your-16-char-app-password
```

or as environment variables (these need the prefix):

```bash
export SERCOMM_PRINTSERVER___EMAIL__SMTP_HOSTS='["smtp.gmail.com:587"]'
export SERCOMM_PRINTSERVER___EMAIL__FROM_ADDRESS=your-email@gmail.com
export SERCOMM_PRINTSERVER___EMAIL__SMTP_USERNAME=your-email@gmail.com
export SERCOMM_PRINTSERVER___EMAIL__SMTP_PASSWORD=your-16-char-app-password
```

#### Send Simple Email

```bash
# Send basic email to one recipient
sercomm-printserver send-email \
    --to recipient@example.com \
    --subject "Test Email" \
    --body "Hello from bitranox!"

# Send to multiple recipients
sercomm-printserver send-email \
    --to user1@example.com \
    --to user2@example.com \
    --subject "Team Update" \
    --body "Please review the latest changes"
```

#### Send HTML Email with Attachments

```bash
sercomm-printserver send-email \
    --to recipient@example.com \
    --subject "Monthly Report" \
    --body "Please find the monthly report attached." \
    --body-html "<h1>Monthly Report</h1><p>See attached PDF for details.</p>" \
    --attachment report.pdf \
    --attachment data.csv
```

#### Send Notifications

For simple plain-text notifications, use the convenience command:

```bash
# Single recipient
sercomm-printserver send-notification \
    --to ops@example.com \
    --subject "Deployment Success" \
    --message "Application deployed successfully to production at $(date)"

# Multiple recipients
sercomm-printserver send-notification \
    --to admin1@example.com \
    --to admin2@example.com \
    --subject "System Alert" \
    --message "Database backup completed successfully"
```

#### Programmatic Email Usage

```python
from pydantic import SecretStr

from sercomm_printserver.adapters.email.sender import EmailConfig
from sercomm_printserver.composition import send_email, send_notification

# Configure email. EmailConfig is a btx_lib_mail ConfMail, so in Python the fields use the
# library's names (smtphosts, smtp_use_starttls, smtp_timeout, smtp_starttls_verify,
# smtp_local_hostname, smtp_delivery_deadline); configuration files keep their keys (smtp_hosts,
# use_starttls, timeout, starttls_verify, local_hostname, delivery_deadline). smtp_password is a SecretStr: it prints as
# '**********' in logs, reprs and dumps, and config.smtp_password.get_secret_value() returns
# the plain text.
config = EmailConfig(
    smtphosts=["smtp.gmail.com:587"],
    from_address="alerts@myapp.com",
    smtp_username="myuser@gmail.com",
    smtp_password=SecretStr("app-password"),
    smtp_timeout=60.0,
)

# Send simple email
send_email(
    config=config,
    recipients="recipient@example.com",
    subject="Test Email",
    body="Hello from Python!",
)

# Send email with HTML and attachments
from pathlib import Path

send_email(
    config=config,
    recipients=["user1@example.com", "user2@example.com"],
    subject="Report",
    body="See attached report",
    body_html="<h1>Report</h1><p>Details in attachment</p>",
    attachments=[Path("report.pdf")],
)

# Send notification
send_notification(
    config=config,
    recipients="ops@example.com",
    subject="Deployment Complete",
    message="Production deployment finished successfully",
)
```

#### Email Troubleshooting

**Connection Failures:**
- Verify SMTP hostname and port are correct
- Check firewall allows outbound connections on SMTP port
- Test connectivity: `telnet smtp.gmail.com 587`

**Authentication Errors:**
- For Gmail: Use App Password, not account password
- Ensure username/password are correct
- Check for 2FA requirements

**Emails Not Arriving:**
- Check recipient's spam folder
- Verify `from_address` is valid and not blacklisted
- Review SMTP server logs for delivery status

## Further Documentation

- [Install Guide](INSTALL.md)
- [Development Handbook](DEVELOPMENT.md)
- [Contributor Guide](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)
- [Module Reference](docs/systemdesign/module_reference.md)
- [License](LICENSE)
