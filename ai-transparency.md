# AI transparency

The author and owner of this project is the human, [@bitranox](https://github.com/bitranox).
Every design and engineering decision is theirs, and they answer for everything published here.
An AI assistant (Claude, run through the Claude Code CLI) was used as a tool along the way,
mostly for the typing and the legwork under that direction. This page says where, plainly, so
you can weigh the work on its merits. The reasoning behind working this way is in
[ai-stance.md](ai-stance.md).

## The human's work

The problem is theirs. SerComm-built print servers (the PS301 and the boxes TRENDnet, Perle,
Netgear and Linksys sold with their own label on it) still run printers in offices and
workshops. Their vendor tools are old Windows programs, and the devices are managed through FTP
"virtual files" where reading the wrong file restarts the device or wipes its settings. The
human wanted a tool that manages, searches for and prints to these devices from any OS and from
scripts, without those traps.

The decisions were the human's:

- the scope: manage, print (LPD and RAW) and find devices, and a Python library as well as a CLI;
- one library for both model lines, with two parallel ports plus one serial, or one parallel;
- a fully typed model of the device's CONFIG file, so a change is validated before it is sent
  and shown as a diff first;
- tiered confirmation: `--yes` for anything that changes the device, plus the device's own name
  for anything that can take it off the network or open it up;
- device search by the FTP greeting alone, with no login, after a production unit on the same
  network stopped answering when it was probed harder;
- the vendor's "ARP trick" for a device whose address is unknown, done natively through
  `ipscout` instead of calling `arp` or `netsh`;
- JSON output for every command, the same envelope as their other tools;
- end-to-end tests against a real PS301, including moving it to another address and back,
  under the rule that no test may endanger the device's firmware.

The human reviewed and corrected the work at each step; what ships is what they signed off on.
Every commit went out under the human's name and authority, with no AI co-author line.

## Where the AI was used

As a tool, under the human's direction, it did the legwork: reading the OEM manuals and firmware
images to extract the CONFIG key table for each model and firmware version; measuring how the
test device actually behaves (which ports are open, how a restart shows, what the password file
needs) when the manuals were silent or wrong; typing the modules, the CLI, the tests and the docs
to the human's design; and laying out the options at each fork for the human to choose from.
None of the decisions, and none of the accountability, were the AI's.

## What's been checked

The gate is `make test`, and CI runs the same checks: Ruff (lint and format), Pyright in strict
mode, the import-linter layer contracts, Bandit, pip-audit, and Pytest with coverage, including
the doctests in the source modules. CI runs them on Linux, macOS and Windows for every Python
version from 3.10 to 3.15. The protocol adapters are tested against small local servers that
speak the device's dialect. The end-to-end suite (`tests/test_e2e_device.py`) runs only on
request, against a real device, and saves the device's configuration before it changes anything.

## Checking it yourself

You do not have to take any of this on faith.

- The source is available. Read `src/sercomm_printserver/`; the module-by-module map is in
  [docs/systemdesign/module_reference.md](docs/systemdesign/module_reference.md).
- What is known about the devices, and how it was found, is in
  [docs/Manual-PS301.md](docs/Manual-PS301.md) and [docs/config-keys.md](docs/config-keys.md).
- The tests live in `tests/`. Run `make test` and see.

If something does not line up, open an issue. That is what they are for.

## License and attribution

The text and code here are under the MIT License (see [LICENSE](LICENSE)). Anthropic's terms put
ownership of model output with the user, so the human owns this and answers for it.
