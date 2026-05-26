---
sidebar_position: 4
title: "Contributing"
description: "How to contribute to Superforecasting Agent."
---

# Contributing

Thank you for contributing to Superforecasting Agent. This guide covers setting up your development environment, choosing the right contribution path, and keeping changes aligned with the fork's forecast-desk objective.

## Contribution Priorities

We value contributions in this order:

1. **Forecast ledger correctness** - data loss, append-only history, resolution provenance, and scoreability
2. **Scoring, calibration, and learning** - Brier/log/proper scores, postmortems, backtests, error profiles, and active lessons
3. **Evidence and source handling** - timestamped evidence, snapshots, reliability metadata, watched sources, and domain adapters
4. **CLI/TUI/dashboard forecast workflows** - forecast lifecycle ergonomics, review queues, alerts, and calibration visibility
5. **Security and robustness** - shell injection, prompt injection, path traversal, retry behavior, and graceful degradation
6. **Cross-platform compatibility** - macOS, Linux, WSL2, and native Windows paths inherited from the runtime
7. **Documentation** - forecast-first docs, compatibility notes, examples, and migration guidance

## Common contribution paths

- Adding a forecast lifecycle feature? Start with `forecasting/ledger.py`, `forecasting/cli.py`, and `tests/forecasting/`.
- Adding an evidence/news/data/market source? Start with `forecasting/source_adapters.py` and `forecasting/extensions.py`.
- Exposing forecast behavior to the agent loop? Start with `tools/forecasting_tool.py`.
- Building a local extension without modifying core? Start with [Build a Superforecasting Agent Plugin](../guides/build-a-superforecasting-agent-plugin.md); this is an inherited plugin surface.
- Building a new inherited runtime tool? Start with [Adding Tools](./adding-tools.md), but prefer forecast ledger actions or plugins first.
- Building a new skill? Start with [Creating Skills](./creating-skills.md).
- Building a new inference provider? Start with [Adding Providers](./adding-providers.md).

## Development Setup

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Git** | With `--recurse-submodules` support, and the `git-lfs` extension installed |
| **Python 3.11+** | uv will install it if missing |
| **uv** | Fast Python package manager ([install](https://docs.astral.sh/uv/)) |
| **Node.js 20+** | Optional — needed for browser tools and WhatsApp bridge (matches root `package.json` engines) |

### Clone and Install

```bash
git clone --recurse-submodules <your-superforecasting-agent-fork-url>
cd superforecasting-agent  # or the inherited checkout name, hermes-agent

# Create venv with Python 3.11
uv venv venv --python 3.11
export VIRTUAL_ENV="$(pwd)/venv"

# Install with all extras (messaging, cron, CLI menus, dev tools)
uv pip install -e ".[all,dev]"

# Optional: browser tools
npm install
```

### Configure for Development

```bash
mkdir -p ~/.superforecasting-agent/{cron,sessions,logs,memories,skills}
cp cli-config.yaml.example ~/.superforecasting-agent/config.yaml
touch ~/.superforecasting-agent/.env

# Add at minimum an LLM provider key:
echo 'OPENROUTER_API_KEY=sk-or-v1-your-key' >> ~/.superforecasting-agent/.env
```

The inherited `~/.hermes` home and `HERMES_HOME` env var remain compatibility paths, but new fork-local development should prefer `~/.superforecasting-agent`, `SUPERFORECASTING_AGENT_HOME`, or `FORECAST_HOME`.

### Run

```bash
# Symlink for global access
mkdir -p ~/.local/bin
ln -sf "$(pwd)/venv/bin/superforecasting-agent" ~/.local/bin/superforecasting-agent
ln -sf "$(pwd)/venv/bin/forecast" ~/.local/bin/forecast

# Verify
superforecasting-agent doctor
forecast status
superforecasting-agent desk -q "Summarize the active forecast desk state."
```

### Run Tests

```bash
scripts/run_tests.sh tests/forecasting tests/test_project_metadata.py -q
```

Run narrower tests for focused edits, then broaden based on blast radius. Use `npm run build` in `website/`, `web/`, or `ui-tui/` when editing those packages.

## Code Style

- **PEP 8** with practical exceptions (no strict line length enforcement)
- **Comments**: Only when explaining non-obvious intent, trade-offs, or API quirks
- **Error handling**: Catch specific exceptions. Use `logger.warning()`/`logger.error()` with `exc_info=True` for unexpected errors
- **Cross-platform**: Never assume Unix (see below)
- **Profile-safe paths**: Never hardcode `~/.hermes` unless you are explicitly documenting compatibility. Use `get_hermes_home()` from `hermes_constants` for code paths and `display_hermes_home()` for user-facing messages.

## Cross-Platform Compatibility

Superforecasting Agent inherits runtime support for **Linux, macOS, WSL2, and native Windows (early beta via PowerShell install)**. Native Windows uses Git Bash from [Git for Windows](https://git-scm.com/download/win) for shell commands. A few features require POSIX kernel primitives and are gated: the dashboard's embedded PTY terminal pane (`/desk` tab, with `/chat` as a compatibility alias) is WSL2-only. The native-Windows path is new and moves fast; if you're doing Windows-heavy development, expect to hit and fix rough edges.

When contributing code, keep these rules in mind:

- **Don't add unguarded `signal.SIGKILL` references.** It's not defined on Windows.  Either route through `gateway.status.terminate_pid(pid, force=True)` (the centralized primitive that does `taskkill /T /F` on Windows and SIGKILL on POSIX), or fall back with `getattr(signal, "SIGKILL", signal.SIGTERM)`.
- **Catch `OSError` alongside `ProcessLookupError` on `os.kill(pid, 0)` probes.** Windows raises `OSError` (WinError 87, "parameter is incorrect") for an already-gone PID instead of `ProcessLookupError`.
- **Don't force the terminal to POSIX semantics.** `os.setsid`, `os.killpg`, `os.getpgid`, `os.fork` all raise on Windows — gate them with `if sys.platform != "win32":` or `if os.name != "nt":`.
- **Open files with an explicit `encoding="utf-8"`.** The Python default on Windows is the system locale (often cp1252), which mojibakes or crashes on non-Latin text.
- **Use `pathlib.Path` / `os.path.join` — never manually concat with `/`.** This matters less for strings the OS gives us back and more for strings we construct to hand to subprocesses.

Key patterns:

### 1. `termios` and `fcntl` are Unix-only

Always catch both `ImportError` and `NotImplementedError`:

```python
try:
    from simple_term_menu import TerminalMenu
    menu = TerminalMenu(options)
    idx = menu.show()
except (ImportError, NotImplementedError):
    # Fallback: numbered menu
    for i, opt in enumerate(options):
        print(f"  {i+1}. {opt}")
    idx = int(input("Choice: ")) - 1
```

### 2. File encoding

Some environments may save `.env` files in non-UTF-8 encodings:

```python
try:
    load_dotenv(env_path)
except UnicodeDecodeError:
    load_dotenv(env_path, encoding="latin-1")
```

### 3. Process management

`os.setsid()`, `os.killpg()`, and signal handling differ across platforms:

```python
import platform
if platform.system() != "Windows":
    kwargs["preexec_fn"] = os.setsid
```

### 4. Path separators

Use `pathlib.Path` instead of string concatenation with `/`.

## Security Considerations

Superforecasting Agent has terminal access. Security matters.

### Existing Protections

| Layer | Implementation |
|-------|---------------|
| **Sudo password piping** | Uses `shlex.quote()` to prevent shell injection |
| **Dangerous command detection** | Regex patterns in `tools/approval.py` with user approval flow |
| **Cron prompt injection** | Scanner blocks instruction-override patterns |
| **Write deny list** | Protected paths resolved via `os.path.realpath()` to prevent symlink bypass |
| **Skills guard** | Security scanner for hub-installed skills |
| **Code execution sandbox** | Child process runs with API keys stripped |
| **Container hardening** | Docker: all capabilities dropped, no privilege escalation, PID limits |

### Contributing Security-Sensitive Code

- Always use `shlex.quote()` when interpolating user input into shell commands
- Resolve symlinks with `os.path.realpath()` before access control checks
- Don't log secrets
- Catch broad exceptions around tool execution
- Test on all platforms if your change touches file paths or processes

## Pull Request Process

### Branch Naming

```
fix/description        # Bug fixes
feat/description       # New features
docs/description       # Documentation
test/description       # Tests
refactor/description   # Code restructuring
```

### Before Submitting

1. **Run focused tests**: `scripts/run_tests.sh <changed-test-files> -q`
2. **Run forecast regressions when touching the desk**: `scripts/run_tests.sh tests/forecasting tests/test_project_metadata.py -q`
3. **Test manually**: run `forecast status` and exercise the code path you changed
4. **Check cross-platform impact**: consider macOS, Linux, WSL2, and native Windows
5. **Keep PRs focused**: One logical change per PR

### PR Description

Include:
- **What** changed and **why**
- **How to test** it
- **What platforms** you tested on
- Reference any related issues

### Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>
```

| Type | Use for |
|------|---------|
| `fix` | Bug fixes |
| `feat` | New features |
| `docs` | Documentation |
| `test` | Tests |
| `refactor` | Code restructuring |
| `chore` | Build, CI, dependency updates |

Scopes: `cli`, `gateway`, `tools`, `skills`, `agent`, `install`, `whatsapp`, `security`

Examples:
```
fix(cli): prevent crash in save_config_value when model is a string
feat(gateway): add WhatsApp multi-user session isolation
fix(security): prevent shell injection in sudo password piping
```

## Reporting Issues

- Use the fork's GitHub Issues when available. Use upstream Hermes issues only for inherited-runtime bugs that reproduce upstream.
- Include: OS, Python version, Superforecasting Agent version (`superforecasting-agent version`), full error traceback
- Include steps to reproduce
- Check existing issues before creating duplicates
- For security vulnerabilities, please report privately

## Community

- **Fork issues**: [teddyjfpender/superforecasting-agent/issues](https://github.com/teddyjfpender/superforecasting-agent/issues)
- **Upstream community Discord**: [discord.gg/NousResearch](https://discord.gg/NousResearch) for inherited-runtime and broader Nous ecosystem discussion
- **GitHub Discussions**: Use fork discussions if enabled; otherwise file design proposals as issues
- **Skills Hub**: Upload specialized skills and share with the community

## License

By contributing, you agree that your contributions will be licensed under the repository's MIT License.
