# Contributing Guide

Thanks for helping improve **sercomm_printserver**. The sections below summarise the day-to-day workflow, highlight the repository automation, and list the checks that must pass before a change is merged.

## 1. Workflow Overview

1. Fork and branch -- use short, imperative branch names (`feature/cli-extension`, `fix/codecov-token`).
2. Make focused commits -- keep unrelated refactors out of the same change.
3. Run `make test` locally before pushing (see the automation note below).
4. Update documentation and changelog entries that are affected by the change.
5. Open a pull request referencing any relevant issues.

## 2. Commits & Pushes

- Commit messages should be imperative (`Add rich handler`, `Fix CLI exit codes`).
- The test harness (`make test`) runs the full lint/type/test pipeline. It creates no commit, but it may raise dependency floors in `pyproject.toml` and apply ruff's formatting and fixes, so review the working tree afterwards.
- `make push` runs the tests, commits and pushes. Give the message with `MSG="..."` (passed to bmk as `BMK_COMMIT_MESSAGE`); without one it prompts. `make help` lists every target.

## 3. Coding Standards

- Keep to the layer rules: domain is pure, then application, adapters and composition. import-linter
  enforces them (`[tool.importlinter]` in `pyproject.toml`); the module map is in
  [docs/systemdesign/module_reference.md](docs/systemdesign/module_reference.md).
- Prefer small, single-purpose modules and functions; avoid mixing orthogonal concerns.
- Free functions and modules use `snake_case`; classes are `PascalCase`.
- Keep runtime dependencies minimal. Use the standard library where practical.

## 4. Tests & Tooling

- `make test` runs Ruff (format + lint), bandit, import-linter, pip-audit, Pyright, and Pytest with coverage (all tests except those marked `integration`; CI runs all except `local_only`). See [DEVELOPMENT.md](DEVELOPMENT.md).
- `make dev` installs the package with its dev extras (`uv pip install -e ".[dev]"`).
- `make codecov` uploads the coverage report. For private repositories set `CODECOV_TOKEN` in your environment or `.env`.
- Test names state the behaviour they pin (`test_check_reset_without_yes_exits_77_and_probes_nothing`), each test checks one behaviour, and OS constraints carry the markers from `pyproject.toml` (`os_agnostic`, `os_windows`, `os_macos`, `os_posix`, `os_linux`).
- Protocol adapters are tested against the loopback fakes in `tests/fake_*_server.py`, use cases against the in-memory adapters (`build_testing`); the tests against a real device are opt-in (see [DEVELOPMENT.md](DEVELOPMENT.md)).
- Whenever you add a CLI behaviour or change metadata, update the relevant story in the `tests/test_cli_*.py` files or `tests/test_metadata.py` so the specification remains complete.

## 5. Documentation Checklist

Before opening a PR, confirm the following:

- [ ] `make test` passes locally.
- [ ] Relevant documentation (`README.md`, `DEVELOPMENT.md`, `docs/systemdesign/*`) is updated.
- [ ] No generated artefacts or virtual environments are committed.
- [ ] Version bumps, when required, are made with `make bump-patch` / `bump-minor` / `bump-major`, which update `pyproject.toml`, `CHANGELOG.md` and `src/sercomm_printserver/__init__conf__.py` together.

## 6. Security & Configuration

- Never commit secrets. Tokens (Codecov, PyPI) belong in `.env` (ignored by git) or CI secrets.
- Logging runs through `lib_log_rich`, whose scrubber hides the fields named in
  `[lib_log_rich] scrub_patterns` (`password`, `secret` and `token` by default, see
  `src/sercomm_printserver/adapters/config/defaultconfig.d/90-logging.toml`). To hide a new
  sensitive field, add a pattern there rather than redacting at the call site.
- Never log or print a device password, and never take one from the command line: `password set`
  reads it from a hidden prompt or a file.

Happy hacking!
