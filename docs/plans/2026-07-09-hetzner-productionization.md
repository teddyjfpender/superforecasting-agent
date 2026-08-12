# Hetzner Productionization — Feature-Complete and Deployable

Date: 2026-07-09 · Branch: `superforecasting-agent-snapshot` · Status: PARTIALLY SHIPPED — reconciled against the tree 2026-07-28

> **Reconciliation 2026-07-28:** P0 and the P1–P3 core shipped (commits `df8117136`
> "P1+P2 — deployable core proven", `61594d90f` "P3 hardening"). Every acceptance
> criterion below now carries an inline status. A box is ticked ONLY where a named
> file/test/artifact mechanically evidences it today (tests re-run green 2026-07-28);
> anything needing a real Hetzner box, a live external account, or an overnight run is
> left unchecked with an explicit marker. Also fixed the same day: `docs/deploy/hetzner.md`
> pinned its install/upgrade one-liners to the fork's dead `main` branch (both 404'd);
> they now pin `superforecasting-agent-snapshot`, and a regression test
> (`tests/test_project_metadata.py::test_fork_repo_urls_pin_live_snapshot_branch_not_dead_main`)
> sweeps docs+scripts so the ref cannot silently rot again.

**The operator's target (verbatim intent):** a user can easily deploy the system on
Hetzner, easily wire it to their Telegram / Slack / Signal (etc.), and SSH into it
from their own terminal to use the TUI. The operator is a lazy prompter by design —
deployment must be a few commands, not a runbook.

This plan is grounded in a deep read of the deploy/gateway/messaging/config/security
surfaces plus live probes run on 2026-07-09. Section 0 is the honest exists-vs-gap
map; P1–P3 are the phased slices with acceptance criteria. The headline: **far more
exists than the folklore says** — the fork inherits a production-grade multi-platform
gateway from upstream hermes (Docker image, systemd installer, Telegram/Signal/
WhatsApp/Slack adapters, pairing security, in-process cron) — and the real gaps are
(a) a Hetzner-shaped bootstrap, (b) the SSH→TUI landing, (c) a forecast-native
`connect` + notification-routing layer on top of the inherited adapters, and
(d) unattended-spend guardrails.

---

## 0. What exists vs what's missing (research findings)

### 0.1 Live probes (run 2026-07-09 on the dev machine; report, don't assume)

| Probe | Result |
|---|---|
| `SKIP_NPM=1 scripts/build-release.sh` | **PASS** — wheel + sdist `superforecasting_agent-0.17.0` built via `uv build`, TUI bundle at `hermes_cli/tui_dist/entry.js` |
| `python -m tui_gateway.entry --http 127.0.0.1:8971` then `GET /health` | **PASS** — boots in <4s, returns `{"protocol_version": 1, "uptime": 3.7, "subscribers": 0}`; log confirms `POST /rpc · GET /events · GET /health` |
| `superforecasting-agent gateway run` (isolated `$SUPERFORECASTING_AGENT_HOME`) | **PASS (headless boot)** — starts "Messaging platforms + cron scheduler"; warns `No user allowlists configured. All unauthorized users will be denied` and `No messaging platforms enabled` (deny-by-default confirmed) |
| `gateway install --help` | **EXISTS** — installs systemd user unit, `--system` boot-time Linux service, `--run-as-user` |
| GitHub release `teddyjfpender/superforecasting-agent` | **REAL** — `v2026.6.30` (published 2026-06-30) with assets `install.sh`, wheel, sdist; the one-line `curl …/releases/latest/download/install.sh \| bash` path is live |
| Docker Hub `teddyjfpender/superforecasting-agent` | **404 — NOT PUBLISHED.** `website/docs/user-guide/docker.md` documents pulling this image; that is currently marketing, not reality |
| Repo-root `./superforecasting-agent gateway --help` on bare system python | Fails wanting `dotenv` — an artifact of running outside the venv; `python-dotenv` IS a base wheel dep. But messaging adapters live in the `[messaging]` extra (`python-telegram-bot`, `slack-bolt`, `discord.py`, …) — a plain pipx install relies on `tools/lazy_deps.py` first-use installs |
| Docker image build | **NOT PROBED** (heavy). `Dockerfile` is fork-branded and complete on paper; treat the build as unverified until CI proves it |

> **Delta re-probed 2026-07-28** (the rows above stay as the 2026-07-09 historical
> record): `ghcr.io/teddyjfpender/superforecasting-agent` is now **published and
> anonymously pullable** — tags `v0.18.0`, `v0.19.0`, `latest`; multi-arch
> `linux/amd64 + linux/arm64` (manifest list fetched and verified). Docker Hub
> (`teddyjfpender/superforecasting-agent`) still does **not** exist (404), and
> `website/docs/user-guide/docker.md` still pulls the bare Docker-Hub image name on
> every example — that doc must move to the ghcr name.

### 0.2 Exists-vs-gap map per pillar

**DEPLOY — mostly exists, unpublished + un-bootstrapped.**
- EXISTS: fork-branded `Dockerfile` (gateway + dashboard + cron in one image, tini,
  non-root UID 10000 with `docker/entrypoint.sh` usermod/gosu remap, `/opt/data`
  volume, `AUTH_JSON_BOOTSTRAP` non-interactive credential seeding);
  `docker-compose.yml` (gateway `restart: unless-stopped` + localhost-only dashboard,
  with real security notes); `scripts/build-release.sh` → pipx wheel with bundled TUI
  + node auto-provision (`hermes_cli/main.py` `ensure_node`: fnm/nvm/proto/brew);
  one-line release installer (`scripts/install-release.sh`, live GitHub release);
  `gateway install [--system]` writes systemd/launchd units natively
  (`scripts/hermes-gateway`); a full NixOS module (`nix/nixosModules.nix`,
  hardened systemd, OCI mode); additive auto-migrations
  (`forecasting/ledger/core.py::_ensure_column`, `CREATE TABLE IF NOT EXISTS` on open).
- GAPS: no published container image; no Hetzner/cloud-init bootstrap; no
  doctor-verified end-to-end fresh-box path; migrations are forward-only with **no
  `PRAGMA user_version` downgrade guard**; docs target Docker Desktop users, not a VPS.

**CRON / HEADLESS LOOPS — exists, but gateway-coupled.**
- The nightly forecast routines (self-check, auto-score, postmortems, thesis
  aggregation, lesson synthesis, deterministic refresh, saturation sweep, free-tier
  warning drain — `forecasting-scheduled-routines.md`) run on an **in-process
  scheduler inside `gateway run`** (`cron/scheduler.py`, `forecasting/cron_runner.py`).
  `schedule install-cron` writes to the internal cron store, **not the OS crontab**,
  despite the name. First committed question auto-installs the nightly routine;
  `install_backup_cron`/`ensure_default_backup_routine` exist (07:30 ledger backup).
- Consequence to state plainly: **if the gateway process is down, nothing forecasts
  overnight.** systemd `Restart=` supervision is therefore load-bearing, not optional.

**SSH / TUI — the TUI is ready; the landing is undesigned.**
- EXISTS: `superforecasting-agent --tui` works over any TTY from the pipx install;
  the TUI spawns `tui_gateway` over stdio (`ui-tui/src/gatewayClient.ts::startSpawnedGateway`),
  or attaches to a WebSocket URL (`*_TUI_GATEWAY_URL`, WS handler mounted in the
  dashboard FastAPI at `/api/ws`); the B4 HTTP+SSE serve mode
  (`tui_gateway/http_server.py`: stdlib `ThreadingHTTPServer`, `POST /rpc`,
  `GET /events` SSE with `Last-Event-ID` resume, `/health`; **refuses non-loopback
  bind without a bearer token**, constant-time compare); headless LLM auth paths
  (`nous` device-code, `hermes_cli/codex_device_flow.py` for ChatGPT OAuth, manual
  callback-URL paste, `website/docs/guides/oauth-over-ssh.md`).
- GAPS: zero ForceCommand/login-shell/tmux design anywhere in the repo; no
  provisioning of a dedicated Unix user; multi-SSH-session semantics undefined
  (each `--tui` spawns its own tui_gateway job runtime; the ledger is WAL-mode so
  concurrent access is safe, but N runtimes duplicate work).

**SLACK — the deepest surface; wiring is a manifest dance, not a command.**
- EXISTS: `tools/slack_tool.py` (post_blocks / post_with_metadata sfp/1 /
  upload_file / read_thread + 5 more verbs); `gateway/platforms/slack_app.py`
  (OAuth install writer, signed Events routes); `gateway/platforms/slack.py`
  (Socket-Mode adapter, 3k lines — **inbound Slack→agent conversation works**,
  thread = session); `forecast slack provision|whoami|share`
  (`forecasting/cli/slack_admin.py`, pinned manifest scopes); policy-gated
  `share_forecast` action. Multiplayer plan M1+M2 shipped
  (`docs/plans/2026-07-05-multiplayer-slack-harness.md`); M3–M6 pending.
- GAPS: the user must paste a manifest at api.slack.com, install the app, and
  capture **two** tokens (xoxb + xapp) by hand; `upload_file` uses deprecated
  `files.upload`; no single guided flow.

**TELEGRAM — a working generic adapter; no forecast surface.**
- EXISTS: `gateway/platforms/telegram.py` (+`telegram_network.py`), bidirectional
  python-telegram-bot long-polling (no inbound port needed), `TELEGRAM_ALLOWED_USERS`
  allowlisting, valid cron delivery target (`cron/scheduler.py::_resolve_delivery_targets`
  supports `telegram`, `telegram:<chat>:<thread>`).
- GAPS: no `forecast`-native Telegram anything — no connect flow, no `/forecast`
  commands, no digest binding. **The referenced "task #136 / §12 telegram action
  surface" does not exist in this repo** (searched all plans, no beads/task store);
  the nearest artifact is `docs/plans/2026-05-02-telegram-dm-user-managed-multisession-topics.md`,
  an unimplemented chat-UX plan (topic lanes) that is orthogonal to productionization.
  P2.2 below is written to BE the missing action-surface spec.

**SIGNAL — honestly: a real inherited adapter with a heavy operational tail.**
- EXISTS: `gateway/platforms/signal.py` (+ rate limiter) — talks to an external
  `signal-cli` daemon over JSON-RPC HTTP + SSE.
- COST: Java `signal-cli` install, phone-number registration (captcha dance),
  daemon supervision as a second service, and signal-cli's notorious
  version-churn against Signal's server API. Benefit over Telegram for a
  single operator: near zero. **Recommendation: keep the adapter documented as an
  expert path; do NOT build a guided flow now** (see P2.5).

**WHATSAPP — works, multi-process, expert-only.**
- `scripts/whatsapp-bridge/bridge.js` (Baileys Node bridge: QR login, `/send`,
  `/messages` long-poll, allowlist, tests) + `gateway/platforms/whatsapp.py`.
  Same verdict as Signal: document, don't productize now.

**NOTIFICATIONS — the sharpest real gap found.**
- The hermes cron router delivers agent output to `origin|local|telegram|slack|all`
  (`cron/scheduler.py::_deliver_result` → `tools/send_message_tool.py`). But the
  forecast-native path dead-ends: `forecast autopilot enable --notify <dest>` stores
  `notification_policy["destination"]` in the ledger and **no code reads it**;
  `forecasting/scheduler.py` threads `deliver="local"` everywhere. Alerts, digests,
  cycle results reach a human today only if the agent explicitly posts (slack_tool /
  `forecast slack share`) or via generic cron `--deliver`. P2.4 closes this.

**MULTI-USER — single-tenant by design; say so.**
- `agent/tenant_runtime.py` is a per-session credential/toggle contextvar — its own
  docstring calls it "the FOUNDATION"; unset = today's process-global behavior.
  `SECURITY.md` §2: "Superforecasting Agent is a single-tenant personal forecasting
  agent"; all callers equally trusted; one `{home}`, one SQLite ledger, one
  `auth.json`. **The recommendation this plan adopts: one box = one operator.**
  Multi-user = multiple instances (separate `{home}`, separate service units), or
  separate boxes. True multi-tenancy is out of scope and should not be promised.

**CONFIG / SECRETS / DATA — strong, Docker-friendly.**
- `forecasting/appconfig.py` (B5): typed key registry, layering
  default < `config.yaml` < env (incl. `{home}/.env`) < override; `forecast config
  doctor` validates known/unknown keys, typo-detects, reports secrets
  presence-only, flags file-vs-env conflicts. Everything env-settable.
- Secrets on disk: `{home}/auth.json` (0600, atomic, locked), `{home}/.env` (0600),
  dir 0700. `AUTH_JSON_BOOTSTRAP` env seeds OAuth non-interactively at first boot
  (entrypoint already guards against clobbering rotated tokens).
- State to persist (the volume): `{home}` — notably `forecasting/forecasting.db`
  (+ `-wal`/`-shm`), `auth.json`, `.env`, `config.yaml`, `identity.json`,
  `workspace/`, `home/`, `cron/`, `sessions/`, `logs/`.
- Backups (C7): `ForecastLedger.backup()` uses the SQLite online-backup API,
  retention 14 daily + 8 weekly, `forecast backup run|list`, integrity via
  `PRAGMA integrity_check`. Gap: nothing ships backups off the box.

**SECURITY / UNATTENDED — gates strong, spend brakes OFF by default.**
- Ledger write gate (F-series) on by default: SQLite connection authorizer denies
  direct INSERTs into gated tables outside `allow_ledger_writes()`
  (`forecasting/ledger/gate.py`); saturation/style hooks observe/block.
- Platform allowlists deny-by-default (probed); DM pairing system exists
  (`gateway/pairing.py`: one-time 8-char codes, expiry, rate limits, lockout) —
  the perfect seam for `forecast connect`.
- **BUT** the jobs policy matrix (`forecasting/jobs/policy.py`) defaults every
  (RunMode × ActionClass) cell to `auto` — the only real brakes on an unattended
  box are `FORECAST_WARNINGS_PAID_BUDGET=3` runs/cycle and the paid min-interval.
  SECURITY.md's stated boundary: "The only security boundary against an adversarial
  LLM is the OS" — internet-facing unattended operation is only in-posture with
  whole-process isolation (Docker) or a locked-down box.
- `WECOM_CALLBACK_HOST` defaults to `0.0.0.0` (`gateway/config.py:1698`) — audit item.

---

## 1. The shape of the deployment (decisions, stated up front)

1. **Two supported install lanes, one bootstrap script.**
   - **Lane A (security-preferred): Docker Compose** — matches SECURITY.md's
     isolation posture for an internet-connected unattended agent; image publish is
     the missing piece.
   - **Lane B (lightweight): pipx wheel + `gateway install --system`** — already
     ~works end-to-end today; agent shell runs on the host (weaker posture; the
     bootstrap compensates with a dedicated user + UFW + no public ports).
   - The bootstrap auto-picks A if Docker is present/installable, else B, and says
     which it chose. A lazy prompter never reads a matrix.
2. **Default network posture: ZERO public inbound ports.** SSH only. Slack via
   Socket Mode (outbound WS), Telegram via long-poll (outbound HTTPS), dashboard via
   `ssh -L`. TLS/reverse-proxy is a P3 opt-in, not a P1 requirement. This deletes
   the largest attack-surface and ops-burden class outright.
3. **SSH lands in tmux wrapping ONE shared TUI** (design in P1.3). Persistence
   across dropped links, one job runtime, N viewers mirror one desk. Raw-shell
   escape hatch retained.
4. **One box = one operator.** Multi-user is explicitly out of scope (see pillar
   map); the plan hardens the single-tenant reality instead of gesturing at tenancy.
5. **Telegram is the productized chat surface after Slack; Signal and WhatsApp stay
   expert-documented.** Build cost and maintenance tail don't clear the bar for a
   guided flow (§P2.5).

---

## P0 — RELEASE ENGINEERING (the formal artifact set)

**Why P0, before P1.** P1.1 ("publish the artifacts") and P1.4 ("upgrade path +
downgrade guard") both assume a *release* exists to deploy. Today there is no
standardized one: `pyproject` has been frozen at `0.17.0` while CalVer tags
(`v2026.7.7.2`) marched on, the image the docs pull is a 404, and "a release" is
whatever `scripts/build-release.sh` happened to emit. P0 makes a release a
**formal, reproducible, machine-verifiable set of artifacts** so everything
downstream — the Hetzner bootstrap, the one-line installer, the compose pull —
resolves against a pinned contract instead of a floating `:latest`.

**Research findings at the 2026-07-09 baseline (superseded by status updates below):**
- `scripts/build-release.sh` → `uv build` wheel+sdist with the bundled TUI
  (`hermes_cli/tui_dist/entry.js`, 4.4 MB) + install scripts; `SKIP_NPM=1`
  reuses `ui-tui/dist/entry.js` for an offline build (verified).
- Two version schemes coexist: `pyproject`/`hermes_cli/__init__.py` SemVer
  (`0.17.0`) and CalVer git tags (`v2026.*`). `scripts/release.py` bumps SemVer
  **and** stamps a CalVer `__release_date__` and keeps `acp_registry/agent.json`
  version-locked (a lint test enforces the ACP lock).
- CI at that baseline: `release.yml` (`v*` push → GitHub Release bundled wheel),
  `upload_to_pypi.yml` (`v20*` CalVer → PyPI trusted-publish, opt-in/dormant),
  `docker-publish.yml` (main push + `release: published` → **Docker Hub**
  `teddyjfpender/superforecasting-agent`, native amd64 + native-arm64-runner
  multi-arch merge, moves `:latest`). No workflow pushes to **ghcr.io**; the
  digest is never recorded anywhere a client can pin.
- The launcher resolves its version from `hermes_cli.__version__`; the installer
  (`scripts/install-release.sh`) resolves the newest release's `.whl` from the
  GitHub Releases API and pipx-installs it — it pins nothing.

### P0.1 The formal artifact set per release `vX.Y.Z`
Every release produces exactly these, all attached to the GitHub Release:
1. **Python wheel** — `superforecasting_agent-X.Y.Z-py3-none-any.whl`, bundling
   `tui_dist` (node auto-provisioned at first launch). The pipx lane, unchanged.
2. **Docker image** — `ghcr.io/teddyjfpender/superforecasting-agent`,
   **multi-arch `linux/amd64 + linux/arm64`** (Hetzner sells both; CAX arm64 is
   cheapest), tagged `vX.Y.Z` **and** `latest`. This is the missing piece P1.1
   was written to close; P0 closes it on ghcr.
3. **`SHA256SUMS`** — over the wheel, sdist, and installer, so a box can verify
   what it downloaded.
4. **`release-manifest.json`** — the machine-readable contract (schema
   `scripts/release-manifest.schema.json`, `schema_version: "1"`): product,
   `version`, `tag`, `released`, `git.{commit,branch}`, per-artifact
   `{name, sha256, size_bytes}` for `wheel|sdist|installer|checksums`, the
   `image.{registry,repository,tags,platforms,digest}` (digest = the pushed
   multi-arch manifest-list digest; `null` in a dry-run), and
   **`min_migration_version`** — the oldest prior release whose on-disk ledger
   this build opens + forward-migrates. That field is the machine-readable half
   of P1.4's `PRAGMA user_version` downgrade guard: the installer refuses to
   deploy a build onto a `{home}` older than its `min_migration_version`.
5. **`CHANGELOG.md` entry** — Keep-a-Changelog + SemVer, derived from
   conventional-commit history since the last tag. Non-empty is a release gate.
6. **The one-line installer, pinned to the manifest** — `install.sh` (staged
   from `install-release.sh`) is attached to every release; the pinned form
   resolves the manifest for the tag and installs exactly that wheel + verifies
   its `SHA256SUMS`. (The manifest-pin resolution in the installer is a P1.2
   fast-follow; the manifest it needs is emitted here in P0.)

### P0.2 Versioning discipline
- **Single source of truth: `pyproject.toml` `version`.** `hermes_cli/__init__.py`
  and `acp_registry/agent.json` are kept byte-locked to it; the readiness gate
  fails on any drift. SemVer `vX.Y.Z` is now **the** release scheme. The dormant
  CalVer/PyPI publisher has been removed; GitHub Releases is the wheel authority.
- **Bump rules:** `feat` → minor, `fix`/`perf` → patch, breaking → major. The
  `wip(...)`/`checkpoint` reality is honored — those commits never trigger a
  release by themselves; a release is only ever a deliberate tag on a version
  that the gate has passed.
- **Release-readiness gate** (`scripts/check-release-ready.sh`, shared by the
  workflow and a pre-tag hook): (a) version consistency across the three files,
  (b) strict-SemVer format, (c) `vX.Y.Z` is not already a tag (version ≠ last
  release), (d) changelog has a non-empty entry for the version; `--strict`
  adds (e) protocol codegen fresh (`check-protocol.sh`) and (f) generated docs
  fresh (`docgen --check`). Suites-green is enforced by the workflow (the `test`
  job gates `release` via `needs:`), and locally by `--with-tests`.

### P0.3 The pipeline
- **`.github/workflows/production-release.yml`** — on a version-tag push, the
  gate enforces strict SemVer and `tag == v<pyproject>`, then Python/E2E/TUI,
  compatibility, container-smoke, artifact, image-digest, and draft-release
  verification run before the Release is published and `latest` advances. It
  is the only publisher; the legacy `release.yml` workflow is deleted.
- **`scripts/release.sh`** — the **offline dry-run twin**:
  same gate → same wheel build → checksums → manifest (image `digest: null`,
  "would push ghcr.io/…:vX.Y.Z,latest") → changelog-scaffold `RELEASE_NOTES.md`.
  It never tags or publishes; this makes a release testable before any public
  state changes while keeping publication in one gated workflow.

**Operator config the pipeline needs (not faked in the workflow):**
- **ghcr.io push needs no secret** — it uses the built-in `GITHUB_TOKEN` with
  `permissions: packages: write` (set in the workflow). The operator must, once:
  enable *Settings → Actions → "Allow GitHub Actions to create and approve
  packages"*, and after the first release set the ghcr package visibility to
  **Public** so the docs' unauthenticated `docker pull ghcr.io/…` works.
- **GitHub Release + assets** use `GITHUB_TOKEN` (`contents: write`) — no secret.
- **Docker Hub mirror is a side effect, not owned here:** publishing the Release
  fires `docker-publish.yml` (`release: published`), which needs the operator's
  `DOCKERHUB_USERNAME`/`DOCKERHUB_TOKEN` secrets. If those aren't set, that
  mirror job fails harmlessly while the ghcr image (the P0 primary) still ships.
- **PyPI is not a release lane.** GitHub Releases owns the signed wheel and installer.

### P0.4 Status — what's BUILT NOW vs what remains
- **Built + tested this arc (repo-only, no external accounts):**
  `scripts/release_manifest.py` + `release-manifest.schema.json` (schema +
  validator, jsonschema with a stdlib fallback); `scripts/check-release-ready.sh`
  (red/green gate); `scripts/release.sh` (dry-run default — **verified: it built
  the full six-artifact set locally**); `production-release.yml`; the version
  debt fixed (`pyproject`/`__init__`/`acp_registry` → **`0.18.0`**) with an
  honest `CHANGELOG.md` (gate lattice, BLF A1–A7, warnings-lifecycle drain, the
  TUI quality arc, and this release-engineering slice). Tests:
  `tests/scripts/test_release_manifest.py`, `tests/scripts/test_release_gate.py`.
- **Deferred (needs a live account / first CI run):** the actual multi-arch
  build on ghcr (P1.1's first run is the Docker-build probe this research
  skipped); the installer's manifest-pin + `SHA256SUMS` verify (P1.2); wiring
  `min_migration_version` to a real `PRAGMA user_version` stamp + refusal (P1.4).
- **Status 2026-07-28:** the first deferred item is DONE — the ghcr multi-arch
  image is live and anonymously pullable (`v0.18.0`, `v0.19.0`, `latest`;
  amd64+arm64 manifest verified). The upgrade lane resolves the release manifest
  and verifies `SHA256SUMS` (`scripts/upgrade.sh::verify_checksum`);
  `min_migration_version` is enforced at upgrade time by
  `scripts/migration_guard.py` (`tests/scripts/test_migration_guard.py` green) —
  the in-DB `PRAGMA user_version` open-time stamp remains unbuilt.

---

## P1 — DEPLOYABLE CORE

### P1.1 Publish the artifacts (close the marketing gap)
The docs already sell `docker pull teddyjfpender/superforecasting-agent`; make it true.
- CI job (extend the existing wheel workflow mirrored by `scripts/build-release.sh`):
  build + push the image to GHCR (and optionally Docker Hub) on tag, **multi-arch
  linux/amd64 + linux/arm64** — Hetzner's cheapest boxes are arm64 CAX.
  First run IS the Docker-build probe this research skipped.
- Keep the wheel release lane as-is (it works — probed). Add `[messaging]` extra to
  the documented pipx line (`pipx install 'superforecasting_agent[messaging] @ …'`)
  or verify `tools/lazy_deps.py` first-use installs inside a pipx venv.
- Consider (not required for P1): a slim headless image variant without Playwright
  Chromium + web build for ~⅓ the size; measure first.

**Status 2026-07-28:** the artifact side is done — the ghcr multi-arch image is live,
anonymously pullable (`v0.18.0`, `v0.19.0`, `latest`; amd64+arm64 manifest verified).
The on-a-real-Hetzner-box runs and the docker.md cleanup remain open.

**Acceptance criteria**
- [ ] `docker pull ghcr.io/teddyjfpender/superforecasting-agent:latest` succeeds on a
      fresh Hetzner CX (amd64) AND CAX (arm64) box. *(the image itself is live,
      multi-arch, anon-pullable — verified 2026-07-28; the pull on real Hetzner
      boxes requires a real box — unverified)*
- [ ] `docker compose up -d` from the repo compose file boots the gateway; `docker
      logs` shows the cron scheduler banner; container survives reboot
      (`restart: unless-stopped`). *(requires a real box with a Docker daemon +
      reboot — unverified)*
- [ ] `website/docs/user-guide/docker.md` image references resolve to a real image.
      *(STILL FALSE as of 2026-07-28 — every docker.md example uses the bare
      Docker-Hub name, which 404s; move them to
      `ghcr.io/teddyjfpender/superforecasting-agent`)*

### P1.2 One-command Hetzner bootstrap (`scripts/hetzner-install.sh` + cloud-init)
A single idempotent script (curl-able from the GitHub release, same lane as
`install-release.sh`) plus an equivalent `cloud-init` user-data file for Hetzner's
"user data" box:
1. Create `forecast` Unix user (no sudo); UFW allow 22 only; enable
   unattended-upgrades; fail2ban optional.
2. Lane pick: Docker present/installable → compose deploy (writes
   `/opt/superforecasting/compose.yml`, volume `~forecast/.superforecasting-agent`);
   else pipx wheel + `sudo superforecasting-agent gateway install --system
   --run-as-user forecast` (probed: flags exist).
3. Seed secrets: prompt-or-env for LLM auth (`AUTH_JSON_BOOTSTRAP` honored by the
   entrypoint today; native lane writes `{home}/auth.json`) and data keys into
   `{home}/.env` (0600).
4. Verify, don't hope: run `forecast config doctor`, `superforecasting-agent gateway
   status`, and the P1.3 SSH-landing self-test; print a red/green summary and the
   exact `ssh forecast@<ip>` line to use next.
5. Idempotent re-run = upgrade/repair.

**Status 2026-07-28:** shipped in-tree — `scripts/hetzner-install.sh` (idempotent
bootstrap, lane pick, acceptance checks), `deploy/cloud-init.yaml`, and the container
proof `scripts/test-fresh-box.sh` (stages 0–5). Static installer guards green in
`tests/deploy/test_deploy_hardening.py`. No real Hetzner box has run any of it.

**Acceptance criteria**
- [ ] Fresh Ubuntu 24.04 Hetzner box: `curl -fsSL …/hetzner-install.sh | bash` then
      `ssh forecast@ip` → TUI. **Operator commands ≤ 3 total** (create server, run
      installer, ssh). *(the chain is scripted end-to-end by
      `scripts/test-fresh-box.sh` in a container; requires a real box — unverified.
      NB the documented curl URL 404'd until 2026-07-28 — it pinned the fork's dead
      `main` branch; fixed to `superforecasting-agent-snapshot` + regression-tested)*
- [ ] Same result via cloud-init user-data with zero interactive steps (secrets via
      user-data env). *(`deploy/cloud-init.yaml` exists and runs the same bootstrap;
      requires a real box — unverified)*
- [x] Installer exits non-zero with a named failing check when doctor/status fail.
      *(shipped: `acceptance()` in `scripts/hetzner-install.sh` — doctor JSON is
      parsed and hard-fails on typo'd/unknown vars + precedence conflicts, gateway
      health and the landing are checked, every failure is recorded by name and the
      script exits 1 listing them)*
- [ ] Re-running the installer on a provisioned box is a no-op/upgrade, never a wipe.
      *(the script is written guard-idempotent at every step, but no automated
      re-run-on-a-provisioned-box proof exists; requires a real box — unverified)*

### P1.3 The SSH story: land IN the TUI (designed properly)
**Design — `forecast` user, per-key ForceCommand, tmux attach-or-create:**
- `/usr/local/bin/forecast-desk` (installed by P1.2):
  ```bash
  #!/usr/bin/env bash
  # SSH landing: attach the shared desk, or honor an explicit escape hatch.
  cmd="${SSH_ORIGINAL_COMMAND:-desk}"
  case "$cmd" in
    shell) exec "$SHELL" -l ;;                      # ssh forecast@box shell
    desk*) exec tmux new-session -A -s "$cmd" \
           "superforecasting-agent --tui" ;;        # desk, desk2, …
    *)     exec "$SHELL" -lc "$cmd" ;;              # scp/rsync/one-offs still work
  esac
  ```
  Wired via `authorized_keys` options
  (`command="/usr/local/bin/forecast-desk",no-X11-forwarding …`) rather than global
  sshd `ForceCommand` — per-key opt-out stays trivial (an admin key without the
  option gets a normal shell). Docker lane: the `desk` branch execs
  `docker exec -it superforecasting-agent-gateway superforecasting-agent --tui`
  inside tmux on the host instead.
- **tmux: YES, by default.** Rationale, not vibes: (a) reconnect-resume across a
  dropped hotel-wifi link is the single most valuable property for a lazy operator;
  (b) each `--tui` spawns its own `tui_gateway` stdio child — one shared session
  means one job runtime instead of N; (c) two SSH clients on `desk` mirror the same
  screen (the correct default for one operator on phone+laptop).
- **Multi-session semantics (documented, not forbidden):** `ssh forecast@box desk2`
  creates an independent second TUI. Safe: the ledger is WAL-mode
  (`forecasting/ledger/core.py:466`, written for exactly "TUI gateway + cron
  reforecasts" concurrency) and the nightly cron lives in the messaging-gateway
  process, not the TUI. Cost: duplicated TUI-side pollers/jobs — fine occasionally,
  wasteful as a habit.
- **Deliberately NOT built now:** a single long-lived tui_gateway that TUIs attach
  to over WS (`*_TUI_GATEWAY_URL` attach mode is real code, but the WS mount lives
  inside the dashboard FastAPI and the session registry is single-operator). tmux
  buys the same UX for zero new code; revisit only if true multi-device concurrent
  independent desks become a want (P3 note).

**Status 2026-07-28:** shipped — `scripts/forecast-desk` (desk/deskN/shell/one-off
routing) + per-key ForceCommand wiring in the installer; the container proof scripts
the landing, both escape hatches, and reconnect-resume (test-fresh-box stages 4a–5).
The container run was not re-executed in this reconciliation; no real box yet.

**Acceptance criteria**
- [ ] `ssh forecast@ip` → TUI visible in <10s on a CX32; no intermediate shell.
      *(landing scripted as test-fresh-box stage 4d; the <10s-on-CX32 number
      requires a real box — unverified)*
- [ ] Kill the SSH connection; `ssh` back → same TUI session, scrollback intact.
      *(scripted as test-fresh-box stage 5 — client killed, tmux session survives;
      not re-run in this pass; real box — unverified)*
- [ ] `ssh forecast@ip shell` → login shell; `scp` a file → works (escape hatches).
      *(scripted as test-fresh-box stages 4b/4c; real box — unverified)*
- [ ] `ssh -t forecast@ip desk2` → second independent TUI; ledger stays uncorrupted
      (run the suite invariant: `forecast doctor` clean after concurrent use).
      *(`forecast-desk` routes `deskN` to independent tmux sessions, but no
      automated concurrent-desk + doctor stage exists anywhere — unverified)*
- [ ] Landing self-test in the installer verifies the whole chain non-interactively
      (`ssh -o BatchMode … 'true'` + tmux session creation). *(partial: installer
      acceptance check (d) verifies forecast-desk + a non-interactive tmux session
      create/kill as the desk user; the in-installer loopback `ssh -o BatchMode` hop
      was not built — the full ssh chain lives in `scripts/test-fresh-box.sh`
      instead)*

### P1.4 Service supervision, volume, and backup (make the nightly loop unkillable)
- systemd: use the existing `gateway install --system` unit (native lane) /
  compose `restart: unless-stopped` (Docker lane). Verify the unit sets
  `Restart=always`, correct `WorkingDirectory`/env, journald logging; patch the
  generator if not. **Document loudly: cron lives inside this process** —
  supervision is what keeps the desk forecasting overnight.
- Backup: ensure `ensure_default_backup_routine` is armed on install (not only on
  first question commit); add `forecast backup verify` (restore latest snapshot to a
  temp path + `integrity_check`) to the nightly routine's report; document off-box
  sync (restic/borg or plain `rsync` of `{home}/forecasting/backups/` in the
  installer's optional step — keep it one flag: `--backup-target user@host:path`).
- Upgrade path: native lane `pipx install --force <new.whl>` + `systemctl restart`;
  Docker lane `docker compose pull && up -d`. Migrations are additive-on-open
  (`_ensure_column`) — safe forward. **Add the missing downgrade guard**: stamp
  `PRAGMA user_version` on schema-touching releases; refuse to open a newer-stamped
  DB with an older binary (clear error naming the versions), and take an automatic
  pre-open backup when the stamp advances.

**Status 2026-07-28:** the upgrade/downgrade guard is shipped and tested
(`scripts/upgrade.sh` + `scripts/migration_guard.py`;
`tests/scripts/test_migration_guard.py` green). `forecast backup run|list` exist
(`forecasting/cli/doctor_admin.py`); a `backup verify` verb was never built.
Supervision/reboot behavior needs a real box.

**Acceptance criteria**
- [ ] `kill -9` the gateway → systemd restarts it; nightly self-check fires the same
      night (assert via `forecast doctor` cron-health panel). *(requires a real box
      + an overnight run — unverified)*
- [ ] Box reboot → gateway + landing both come back with no operator action.
      *(requires a real box — unverified)*
- [ ] Nightly backup file appears; `forecast backup verify` green; documented restore
      drill executed once for real (fresh box + backup → working desk).
      *(`forecast backup run|list` shipped; the `backup verify` verb was NOT built
      and the restore drill has not been executed — requires a real box/overnight —
      unverified)*
- [x] Old binary vs newer DB → loud refusal, zero writes (new test). *(shipped as
      the upgrade-time migration guard: `scripts/upgrade.sh` runs
      `scripts/migration_guard.py` BEFORE switching anything — refuses a downgrade
      or a below-`min_migration_version` build with exit 3 and zero writes;
      `tests/scripts/test_migration_guard.py` green 2026-07-28. Precision: the
      in-DB `PRAGMA user_version` open-time refusal was NOT built — the guard
      prevents the state at upgrade time; a manually-installed old binary would not
      be refused at DB open)*

### P1.5 Secrets + headless auth (no browser on the box, ever required)
- All secrets via env or `{home}/.env`/`auth.json` (exists). `forecast config
  doctor` is the gate — the installer runs it and refuses to declare success on red.
- Headless LLM auth over SSH, documented as THE path in the bootstrap output:
  `nous` (device-code), `openai-codex` (`hermes_cli/codex_device_flow.py` device
  flow), and for browser-bound providers (xai/qwen/gemini) the existing manual
  callback-paste + `oauth-over-ssh.md` port-forward recipe.

**Status 2026-07-28:** doctor-side guarantees are tested and green
(`tests/forecasting/test_appconfig.py`, 24 passed 2026-07-28); the headless
device-flow code paths exist. The on-a-fresh-box auth run and the installer-output
secrecy regression test remain open.

**Acceptance criteria**
- [ ] On a fresh box with no browser: complete provider auth entirely inside the SSH
      session for nous AND openai-codex; token lands in `{home}/auth.json` (0600).
      *(device flows exist in code — `nous` device-code,
      `hermes_cli/codex_device_flow.py`; completing them needs a fresh box + live
      provider accounts — unverified)*
- [x] `forecast config doctor` red on a missing/typo'd key names the key and layer.
      *(`test_doctor_flags_unknown_typo_var` +
      `test_doctor_reports_file_vs_env_precedence_conflict` green; the installer's
      acceptance parses doctor JSON and hard-fails on exactly these by name)*
- [ ] No secret value ever printed by installer or doctor (presence-only — existing
      behavior, add a regression test on the installer output). *(doctor half
      proven — `test_doctor_secret_presence_never_leaks_value` green; the
      regression test on the INSTALLER's output was not added — unverified)*

---

## P2 — MESSAGING WIRING (`forecast connect <surface>`)

### P2.1 The `connect` framework (one UX, per-surface plugins)
A new `forecast connect <surface>` guided flow (TTY wizard + `--non-interactive`
flags), built almost entirely from existing seams:
- token capture + validation (per-surface probe call),
- config write to `{home}/.env` / `config.yaml` (via `forecasting/api_keys.py`
  0600 writer + appconfig keys),
- gateway restart (`gateway restart` exists),
- **chat binding via the inherited pairing system** (`gateway/pairing.py` one-time
  codes — already stronger than static allowlists): the operator DMs the bot, gets
  a code, runs `forecast connect <surface> --approve <CODE>`,
- verification ping through the platform adapter, and
- registration of the binding as a **notification destination** (P2.4's store).
`gateway setup` (the inherited generic wizard) remains for exotic platforms.

**Status 2026-07-28:** shipped — the `forecast connect` framework
(`forecasting/cli/connect_admin.py`) + notify destination registration; suites green
2026-07-28 (`tests/forecasting/test_connect_flow.py`, `test_notify_cli.py`).

**Acceptance criteria**
- [x] `forecast connect` with no args lists surfaces with an honest status column
      (connected / available / expert-only).
      *(`test_connect_list_shows_all_surfaces`,
      `test_connect_listing_marks_available_and_deferred`,
      `test_connect_listing_marks_connected` — green)*
- [ ] Each productized surface: wall-clock ≤5 min from command to received test
      message, measured on a fresh box. *(the flows are tested end-to-end with the
      HTTP seam stubbed; the wall-clock measurement needs a fresh box + live
      accounts — unverified)*
- [x] Doctor gains a `connections` section (surface, bound chat, last delivery).
      *(`forecasting/appconfig.py::_connections_report` — surfaces with
      token-presence, bound routes, per-route last delivery status/health;
      `test_config_doctor_has_connections_section` green)*

### P2.2 Telegram (the action surface this plan adopts as "the #136 intent")
The in-repo referent for "task #136 / §12" does not exist (see §0.2); this slice is
written to be that spec.
- **Connect flow:** BotFather token paste → `getMe` validation → write
  `TELEGRAM_BOT_TOKEN` → restart gateway → pairing-code DM binding → test digest.
  Long-polling only — no inbound port, consistent with the zero-inbound posture.
- **Action surface (bounded, forecast-native):** `/forecast list`,
  `/forecast show <id>` (probability + band + last-updated + one-line rationale),
  `/forecast why <id>` (latest analyst note), `/digest on|off`, `/alerts on|off`.
  Read-only against the ledger; anything mutating goes through the normal agent
  session path the adapter already provides (message → gateway session), inheriting
  ledger gates + jobs policy.
- **Deliveries:** nightly self-check digest + alert pushes via P2.4's router.
- The 2026-05-02 multisession-topics plan stays orthogonal/deferred — it's chat-UX
  lanes, not productionization; sequence it only after the action surface earns use.

**Status 2026-07-28:** the connect flow + digest transport shipped
(`forecasting/transports/telegram.py`; connect-flow suite green incl.
`test_acceptance_connect_telegram_one_command_then_digest`, HTTP stubbed). The
`/forecast list|show|why` action surface was NOT built — that half of this slice
remains open.

**Acceptance criteria**
- [ ] Fresh box: `forecast connect telegram` → paste token → DM bot → approve code →
      test card arrives. ≤5 min. *(flow + stubbed-transport acceptance test green;
      the fresh-box run with a live bot requires a real box + live account —
      unverified)*
- [ ] Nightly self-check digest arrives in the bound chat (assert next morning).
      *(requires an overnight run on a live binding — unverified)*
- [ ] `/forecast show <id>` returns the card; unknown users get denied (allowlist/
      pairing enforced — probe with a second Telegram account). *(NOT BUILT — no
      `/forecast` command surface exists in the transport or the gateway adapter)*
- [ ] Gateway offline → commands queue nothing silently; bot down is visible in
      `forecast doctor` connections. *(partial: doctor connections rows carry
      last-delivery status and a `healthy` flag; no offline-queue behavior test
      exists — unverified)*

### P2.3 Slack (finish the user-facing story on the existing OAuth)
- Wrap the shipped pieces into `forecast connect slack`:
  `provision` manifest emit → open-this-URL instruction (manifest paste at
  api.slack.com is a **Slack platform constraint** — say so in the flow, don't fake
  automation) → capture xoxb+xapp (paste, or the existing OAuth redirect writer
  `slack_app.py::install_from_oauth_code` when the operator opts into a temporary
  loopback + `ssh -L`) → `whoami` verification → channel binding → test sfp/1 card.
- Socket Mode is the default transport (no public URL). The Events-API HTTP path
  stays available behind P3.1's proxy for org installs.
- Fix `upload_file` off deprecated `files.upload` →
  `files.getUploadURLExternal`/`completeUploadExternal`.
- Multiplayer M3–M6 (import pipeline, Delphi-in-Slack, provisioning automation,
  slash parity) remain a separate track — not required for "wired up."

**Status 2026-07-28:** `forecast connect slack` shipped (manifest → whoami-green
gate → test card; `test_slack_connect_*` green, HTTP stubbed). File upload is STILL
on the deprecated `files.upload` (`tools/slack_tool.py` marks the migration a
fast-follow) — that criterion is honestly unmet.

**Acceptance criteria**
- [ ] One command + one browser paste (on the operator's laptop, not the box) →
      `forecast slack whoami` green, test card in the chosen channel. *(flow tested
      with stubbed HTTP — `test_slack_connect_happy_path` green; the live run needs
      a real Slack workspace — unverified)*
- [ ] Inbound `@agent` mention in a thread starts a working session (already ships —
      keep a regression check in the connect verifier). *(the inbound path is
      inherited and unchanged — `gateway/platforms/slack.py`; the regression check
      inside the connect verifier was NOT added)*
- [ ] File upload works against the non-deprecated API. *(NOT DONE —
      `tools/slack_tool.py` still calls `files.upload`)*

### P2.4 Unified notification routing (close the dead-end)
The one genuinely missing subsystem. Build `forecasting/notify.py`:
- **Destination store:** implement the reader for the already-persisted
  `notification_policy["destination"]` (autopilot `--notify` currently writes into
  the void) + per-question/portfolio/global destinations registered by P2.1.
- **Render:** reuse the sfp/1 Block Kit cards for Slack; compact markdown for
  Telegram; plain text fallback for anything `send_message_tool` reaches.
- **Deliver:** through the gateway platform adapters / `send_message_tool`
  (`cron/scheduler.py::_resolve_delivery_targets` grammar: `slack:<chan>`,
  `telegram:<chat>[:<thread>]`), with per-destination failure isolation + retry/
  backoff logged to the ledger (alert on persistent failure — the alerts system
  exists).
- **Wire the callers:** nightly self-check digest, alert sweeps (respecting the
  free-tier drain), resolution/scoring events, quorum verdicts, `cycle --notify`.

**Status 2026-07-28:** SHIPPED — `forecasting/notify.py` router (event classes,
multi-surface fan-out, failure isolation, `event_id` dedupe, dead-destination
alerts), wired into autopilot (`forecasting/cli/refresh_cycle.py`) and the nightly
cron digest (`forecasting/cron_runner.py`); router/CLI suites green 2026-07-28
(`tests/forecasting/test_notify_router.py`, `test_notify_cli.py`).

**Acceptance criteria**
- [x] `forecast autopilot enable --notify telegram:<chat>` actually delivers (the
      current silent no-op becomes a test). *(the dead-end is closed: autopilot
      enable registers a real router binding —
      `forecasting/cli/refresh_cycle.py` → `notify.register_destination`; binding +
      delivery covered by `test_register_destination_persists_readable_binding` and
      the router fan-out/delivery tests, green. Delivery to a live Telegram chat is
      exercised through the stubbed wire, not a live bot)*
- [x] One nightly digest per destination, not per question; dedupe proven by test.
      *(`forecasting/cron_runner.py` delivers the sweep digest once per destination
      with a per-sweep `event_id`; `test_dedupe_by_event_id` green)*
- [x] A dead destination (revoked token) produces a ledger alert within one cycle,
      never a crash of the routine.
      *(`test_deliver_digest_alerts_on_dead_destination`,
      `test_failure_is_isolated_and_recorded`,
      `test_sender_exception_does_not_crash_router` — green)*

### P2.5 Signal + WhatsApp: the honest call — DEFER the guided flows
- **Signal:** the adapter is real (`gateway/platforms/signal.py`, signal-cli
  JSON-RPC + SSE) but a guided flow means owning: Java runtime install, phone-number
  registration + captcha, a second supervised daemon, and signal-cli's breakage
  cadence against Signal server changes. That is the single largest ongoing
  maintenance line-item in this plan for a surface with ~zero capability delta over
  Telegram for one operator. **Ship: a tested expert-path doc (daemon systemd unit
  sample + env vars) + `forecast connect signal` printing that doc.** Build the
  guided flow only on demonstrated demand.
- **WhatsApp:** Baileys bridge works but is an unofficial-API account-ban risk with
  a second Node process; same verdict, same doc treatment.

**Status 2026-07-28:** honored as written — `forecast connect signal|whatsapp` print
the one-line deferred/expert notice (tests green); the once-for-real wiring of each
on a test box has not happened.

**Acceptance criteria**
- [ ] `forecast connect signal|whatsapp` prints the expert path + status instead of
      pretending; docs verified once by actually wiring each on a test box.
      *(the honest print is shipped and tested —
      `test_connect_signal_prints_deferred`,
      `test_deferred_notice_is_one_honest_line`; verifying the expert docs by
      actually wiring each needs a test box + live accounts — unverified)*
- [x] Decision recorded here; revisit trigger = operator asks twice. *(recorded in
      this section and enforced in the connect listing's deferred status)*

---

## P3 — HARDENING / MULTI-USER REALITY

### P3.1 Network exposure and TLS (opt-in, because the default is zero-inbound)
- Default posture (P1) already needs no TLS. This slice is the opt-in recipe for
  the three things that ever want a public port: dashboard, OpenAI-compatible API
  server (`gateway/platforms/api_server.py`, `API_SERVER_KEY` mandatory — good),
  Slack Events HTTP mode.
- Ship a Caddy sidecar recipe (compose profile + native unit): TLS via ACME,
  `basic_auth` in front of the dashboard (its code already anticipates Caddy),
  reverse-proxy with SSE buffering off. Recommend Tailscale as the preferred
  alternative to any public port.
- Audit items: `WECOM_CALLBACK_HOST=0.0.0.0` default; confirm the forecast
  webbridge (`forecasting/webbridge.py`, no auth) stays hard-pinned loopback and
  dev-only; dashboard `--insecure` never appears in any shipped unit/compose.

**Status 2026-07-28:** recipe + gates shipped — `deploy/caddy/` (Caddyfile + `tls`
compose profile, SSE-safe) and the shipped-artifact gates in
`tests/deploy/test_deploy_hardening.py` (green). The nmap and live-TLS checks need a
real box + domain.

**Acceptance criteria**
- [ ] `nmap` a default P1 box from outside: port 22 only. *(requires a real box —
      unverified)*
- [ ] With the Caddy profile: dashboard reachable over HTTPS with auth; SSE events
      stream (no proxy buffering); certificate auto-renews. *(the recipe exists and
      is statically tested — `test_caddy_recipe_present_and_sse_safe`; a live
      domain, cert issuance, and renewal need a real box — unverified)*
- [x] Grep-gate in CI: no `--insecure`, no `0.0.0.0` binds in shipped units/compose.
      *(shipped as pytest rather than a literal grep step:
      `test_no_insecure_flag_in_shipped_artifacts` +
      `test_no_public_bind_in_shipped_artifacts` sweep the shipped units/compose
      and run in the CI test suite — green)*

### P3.2 Spend and rate guards for an unattended box
- Flip the unattended default: bootstrap sets `FORECAST_POLICY_CRON_LLM_SPEND`
  (and peer cron cells) to a bounded mode, keeps `FORECAST_WARNINGS_PAID_BUDGET`
  explicit in `.env` with a comment, sets paid min-interval.
- Add a **monthly spend ledger + hard cap**: count agent-run spend classes in the
  ledger (the jobs policy already classifies actions); when the cap trips, paid
  actions degrade to `ask` and an alert fires to the P2.4 destinations.
- `forecast config doctor` warns when policy is all-`auto` on a box whose install
  method is `docker`/server (the `.install_method` stamp exists).

**Status 2026-07-28:** SHIPPED — `forecasting/budget.py` daily/monthly token+USD
ceilings enforced at the `authorize(LLM_SPEND)` chokepoint (`BudgetExceeded` is
`PolicyRefused`), breach → high-severity ledger alert + notify; the bootstrap seeds
the guards (`test_installer_seeds_spend_guards`); `tests/forecasting/test_budget.py`
green 2026-07-28.

**Acceptance criteria**
- [x] Simulated runaway (looping paid reforecast) halts at the cap with an alert;
      free-tier drain continues unaffected.
      *(`test_authorize_llm_spend_refused_over_budget`,
      `test_enforce_over_budget_fires_alert_and_notify`,
      `test_budget_exceeded_is_policy_refused` — green. The zero-spend drain never
      enters the `authorize(LLM_SPEND)` chokepoint, so it is structurally outside
      the gate rather than separately tested)*
- [x] Doctor shows current month spend estimate + cap headroom. *(doctor `budgets`
      section — `forecasting/appconfig.py::_budgets_report` →
      `budget.status_report()` usage vs ceilings + headroom;
      `test_status_report_shape` green)*

### P3.3 Observability (enough, not a platform)
- Logs: journald (native) / `docker logs` (compose) already structured; add log
  rotation config for `{home}/logs/`.
- Status: `superforecasting-agent gateway status --json` (extend the existing
  status verb) exposing: uptime, platforms connected, cron last-run/next-run,
  ledger size, last backup age, month spend. The nightly routine optionally pings a
  dead-man's-switch URL (healthchecks.io style, one env var) — the cheapest
  possible "the box went quiet" alarm for a lazy operator.
- Keep `/health` on the B4 server and api_server as-is.

**Status 2026-07-28:** shipped DIFFERENTLY than written — observability landed as
the token-gated HTTP `GET /status` + enriched `/health`
(`tui_gateway/http_server.py`: version, uptime, ledger_ok, cron last/next-run,
jobs_active, spend-today; pinned by `tests/tui_gateway/test_http_server.py`, green
2026-07-28) plus a structured per-request log line. The `gateway status --json` CLI
verb and the dead-man ping were not built.

**Acceptance criteria**
- [ ] `gateway status --json | jq` returns all fields above. *(superseded in
      substance by the token-gated `GET /status` carrying these fields; the literal
      CLI verb was not built — left unticked for that reason)*
- [ ] Stop the gateway for 26h on a test box → dead-man ping alarm fires. *(the
      dead-man ping was not built; would also require a 26h live run — unverified)*

### P3.4 Auth on the HTTP gateway + the multi-user statement
- B4 HTTP+SSE already refuses non-loopback without a bearer token (probed/verified);
  keep single-shared-token semantics and document it as **operator-grade, not
  user-grade** auth. If the dashboard/API go public, they sit behind P3.1's proxy
  auth in addition to their own tokens.
- **Multi-user: one box = one operator, stated in README/docs.** The supported
  multi-person patterns are: (a) N instances with N `{home}`s and service units on
  one big box, (b) Slack/Telegram group surfaces where teammates talk to the ONE
  operator's agent under its allowlists (this is what the multiplayer harness is
  for). `tenant_runtime` remains an internal seam; finishing the staged
  `os.environ`-reader migration is tracked in the capability-hardening arc, not
  promised here.

**Status 2026-07-28:** the tenancy statement shipped
(`docs/deploy/hetzner.md` §"One box = one operator" + `SECURITY.md` §2). The
two-instance smoke test does not exist.

**Acceptance criteria**
- [x] Docs state the tenancy model in one paragraph; no surface implies otherwise.
      *(`docs/deploy/hetzner.md` closes with exactly this paragraph, consistent
      with `SECURITY.md` §2; no shipped surface promises multi-tenancy —
      `tenant_runtime` remains an internal seam)*
- [ ] Two-instance-one-box pattern documented and smoke-tested (distinct homes,
      ports, service names; both nightly loops fire). *(only a passing mention in
      hetzner.md; neither fully documented nor smoke-tested — unverified)*

---

## Honesty appendix

**Genuinely done today (verified):** wheel + bundled-TUI release with live GitHub
one-liner; headless gateway boot with in-process cron; systemd/launchd installer
verbs; deny-by-default platform allowlists + pairing; Slack inbound/outbound with
sfp/1 + provision/whoami/share; Telegram/Signal/WhatsApp/Discord generic adapters;
typed config + config doctor; WAL ledger + online backup + retention; ledger write
gates; B4 HTTP+SSE with token enforcement; device-code LLM auth suitable for SSH.
**Shipped since and test-evidenced (2026-07-28):** the Hetzner bootstrap + SSH→TUI
landing + fresh-box container proof (P1.2/P1.3 scripts); the upgrade/migration
guard; the notify router + `forecast connect` telegram/slack; box-level spend
ceilings + doctor budgets/connections sections; gateway HTTP bearer auth on every
route; the ghcr multi-arch image, live and anonymously pullable.

**Marketing vs reality (corrected 2026-07-28):** the container image IS now
published — `ghcr.io/teddyjfpender/superforecasting-agent` (`v0.18.0`, `v0.19.0`,
`latest`; multi-arch amd64+arm64; anonymously pullable — token + tags-list +
manifest verified 2026-07-28), so the original "unpublished (404)" claim is stale.
What is STILL marketing: `website/docs/user-guide/docker.md` pulls the bare
Docker-Hub image name in every example, and that registry entry does not exist
(404) — the doc must move to the ghcr name. Also corrected: `autopilot --notify` is
no longer a dead-end — it registers a real router binding (P2.4, shipped + tested).
Still true: `schedule install-cron` never touches the OS crontab; `tenant_runtime`
is plumbing, not tenancy; the forecast webbridge is dev-only loopback; multiplayer
M3–M6 are plans.

**Maintenance surface each choice adds:** tmux+ForceCommand ≈ zero. Telegram
long-poll ≈ low (one token, official API). Slack ≈ medium (manifest scope drift,
files API migration). Caddy ≈ low (only if opted in). GHCR multi-arch image ≈
medium (base bumps, Playwright weight). Signal ≈ HIGH (Java daemon + registration +
churn) — the reason it's deferred. WhatsApp ≈ high + ban risk — deferred.

**Riskiest unknowns (re-stated 2026-07-28):** (1) the chain is container-proven in
script form (`scripts/test-fresh-box.sh`) but has still never run on a REAL Hetzner
box — cloud-init, boot-time systemd units, volumes, UFW, and overnight cron on real
hardware remain the open risk; P1.2's AC is the test. (2) The Docker image
build/publish question is RESOLVED — the ghcr multi-arch image is live and
anonymously pullable (verified 2026-07-28). (3) Unattended spend: P3.2 shipped —
box-level ceilings are enforced at `authorize(LLM_SPEND)` and the bootstrap seeds
the guards (`test_installer_seeds_spend_guards`); the residual risk is an operator
raising or unsetting them, plus the still-default-`auto` policy matrix beneath the
ceilings.

## Suggested sequence
- **Week 1:** P1.1 (CI image) + P1.2 (bootstrap) + P1.3 (SSH landing) — a usable box.
- **Week 2:** P1.4–P1.6 (supervision/backup/upgrade guard/headless auth polish) +
  P2.1 framework.
- **Week 3:** P2.4 notification router (the real feature gap) + P2.2 Telegram.
- **Week 4:** P2.3 Slack finish + P2.5 expert docs + P3.1/P3.2 hardening defaults.
- **Ongoing:** P3.3 observability, P3.4 docs; multiplayer M3+ as a separate track.
