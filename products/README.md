# Product distributions

The monorepo builds separate Python wheels. Product versions are independent;
compatibility is determined by the host's wire version and operation capabilities.

| Product | Installation | Runtime requirements |
| --- | --- | --- |
| Backend and CLI | `pip install superforecasting_agent-*.whl` | Python 3.11–3.13; no Node or bundled TUI/web assets |
| Terminal | `pip install superforecasting_agent_tui-*.whl` | Python 3.11–3.13 and Node 20+; local backend or remote WebSocket host |
| Optional web integration | `pip install 'superforecasting_agent-<version>-py3-none-any.whl[web]'` | Backend plus FastAPI/Uvicorn; presentation assets are separate |

Build both products after the contributor bootstrap:

```sh
python3 scripts/build_profiles.py
python3 scripts/verify_profiles.py dist/profiles --python .venv/bin/python
```

`build_profiles.py --profile backend` does not invoke npm or Node. The backend
wheel is built from a source archive in a clean build environment; the builder
rejects UI assets in the resulting backend wheel. `--profile tui` builds only the
terminal wheel. Building the terminal directly without compiling Ink fails rather
than producing an incomplete installation.

The verifier creates fresh environments outside the checkout, checks dependency
consistency, runs create/update/resolve/score with Node absent from PATH, checks a
terminal-only installation without backend imports, launches the installed Ink
client against both a separate local backend and an authenticated WebSocket
host to score a durable forecast and exit cleanly on POSIX, verifies companion
discovery, and checks the optional web integration and credential-free host logs. Remote `--check` validates local
prerequisites only; host compatibility is checked when connecting. The installed
PTY exercise explicitly skips native Windows; it does not establish ConPTY
coverage or remote-network recovery.

Install both wheels into one environment to use `superforecasting-agent tui`.
Alternatively, run the terminal distribution directly:

```sh
superforecasting-agent-tui --python /path/to/backend/venv/bin/python
superforecasting-agent-tui --gateway-url 'wss://your-host/api/ws?token=...'
superforecasting-agent-tui --check --gateway-url 'wss://your-host/api/ws?token=...'
```

The remote URL must identify the existing authenticated WebSocket gateway, not
its HTTP/SSE endpoint. Explicit `SUPERFORECASTING_AGENT_TUI_DIR` bundles and older
wheel-bundled installations remain compatible launcher inputs. Backend and TUI
versions that cannot satisfy the required protocol/capabilities fail before Ink
session bootstrap.

Release assembly uses the same independent product builder and records the
terminal wheel separately in the manifest and checksums. With `RELEASE_WITH_WEB=1`,
it also produces `dashboard-assets.tar.gz`; extract that archive and set
`SUPERFORECASTING_AGENT_WEB_DIST` to its directory for the optional dashboard.

Installer selection and upgrade automation still need reconciliation for releases
containing multiple wheels before publication. Build/verification commands do not
publish packages.

## Headless protocol host

The backend also provides `superforecasting-agent-host` (or
`python -m superforecasting_agent.hosting`). It serves the same `/api/ws` protocol
used by the terminal without loading the dashboard application. Install the
backend wheel with its existing `[web]` extra for FastAPI/Uvicorn dependencies.
It needs neither Node nor frontend assets.

Read authentication from a private token file and choose the active data profile:

```sh
SUPERFORECASTING_AGENT_HOME=/srv/forecast \
  superforecasting-agent-host --host 127.0.0.1 --port 8642 \
  --token-file /srv/forecast/host.token
```

For VPS access, forward the loopback port over SSH or put an authenticated TLS
reverse proxy in front of it. The terminal connects using `--gateway-url` as above.
The host accepts a Bearer authorization header or the terminal's token query
field; an explicit invalid header cannot fall back to a valid query token.
Browser clients must additionally match an exact `--allow-origin` value. Native
clients without an Origin header are supported. HTTP access logging is disabled. WebSocket handshake logs redact query strings
for both accepted and rejected connections.

This exposes the existing runtime operations and protocol negotiation. Full
host/session lifetime ownership and installed remote-terminal recovery qualification
remain tracked in the product-boundaries plan; this entrypoint alone does not
establish those guarantees.

The POSIX release installer installs both manifest-selected wheels by default.
Use `INSTALL_TUI=0 bash install.sh` for a backend-only environment. All selected
artifacts are verified before installation begins. The PowerShell installer supports the same selection with `-BackendOnly`.
The VPS upgrader now reuses POSIX verification and supports `INSTALL_TUI=0`
and `FORECAST_TUI_WHEEL` for local companion upgrades. Keep `install-release.sh`
beside `upgrade.sh` and its migration guard. Hetzner first installation uses the same verified staging owner and accepts
a local `FORECAST_TUI_WHEEL` companion. Fresh Ubuntu ARM64 container provisioning, SSH/TUI launch and tmux reconnect
have passed with the separate wheels. Native Windows execution of the new
fixture checks remains pending.
