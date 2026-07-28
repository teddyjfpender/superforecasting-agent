# Deploy the Superforecasting Agent on Hetzner

A production deployment in **three commands**: create a box, run the bootstrap,
SSH into the desk. Everything downstream — the systemd supervision, the nightly
in-process cron, the daily ledger backup, the SSH→TUI landing, the upgrade
guard — is wired by one idempotent script.

> Design contract: `docs/plans/2026-07-09-hetzner-productionization.md` (P1).

---

## The three-command quickstart

```bash
# 1. Create a box (arm64 CAX is Hetzner's cheapest; amd64 CX works too).
hcloud server create --name desk --type cax21 --image ubuntu-24.04 \
    --ssh-key my-key

# 2. Bootstrap it (idempotent; re-run to upgrade/repair). The desk key is the
#    one that will LAND IN THE TUI.
ssh root@<ip> 'curl -fsSL \
  https://raw.githubusercontent.com/teddyjfpender/superforecasting-agent/superforecasting-agent-snapshot/scripts/hetzner-install.sh \
  | SSH_PUBKEY="'"$(cat ~/.ssh/id_ed25519.pub)"'" bash'

# 3. Land straight in the desk.
ssh forecast@<ip>
```

Zero-interaction alternative: paste **`deploy/cloud-init.yaml`** (with the three
placeholders filled) into Hetzner's *Cloud config* field at create time. First
boot runs the same bootstrap with no interactive steps.

---

## The blessed install lane — and why

**Docker Compose is the preferred lane; the pipx native lane is the automatic
fallback.** The bootstrap picks Docker when the daemon is present/usable and the
image resolves, otherwise pipx — and tells you which it chose.

The tie-break is `SECURITY.md`: *"the only security boundary against an
adversarial LLM is the OS."* An unattended, internet-connected agent that spends
money and holds OAuth tokens wants **whole-process isolation**, which Docker's
container boundary provides (`restart: unless-stopped` survives reboot). The
pipx lane runs the agent shell on the host — a weaker posture the bootstrap
compensates for with a dedicated unprivileged `forecast` user, UFW allowing only
port 22, and zero public ports. The pipx lane is fully supported and works
end-to-end with **no registry dependency**, so it is what a fresh box uses until
the operator cuts a release that publishes the multi-arch image to ghcr.

Force a lane with `LANE=docker` or `LANE=pipx`.

---

## Network posture: zero public inbound ports

The default is **SSH (22) only**. No dashboard port, no webhook port, nothing
else. This is possible because every messaging surface is outbound:

- **Slack** → Socket Mode (outbound WebSocket)
- **Telegram** → long-poll (outbound HTTPS)
- **Dashboard** → reached with `ssh -L 9119:localhost:9119 forecast@<ip>`

TLS / reverse-proxy is a later opt-in (P3), never a P1 requirement. `nmap` a
default box from outside and you see port 22 alone.

---

## The SSH story: you land IN the TUI

`ssh forecast@<ip>` drops you straight into the terminal desk — no intermediate
shell. This is wired with a **per-key `ForceCommand`** (not a global sshd one),
so an admin key without the option still gets a normal shell:

```
# ~forecast/.ssh/authorized_keys (written by the bootstrap from SSH_PUBKEY)
command="/usr/local/bin/forecast-desk",no-agent-forwarding,no-X11-forwarding,no-port-forwarding ssh-ed25519 AAAA... you@laptop
```

`/usr/local/bin/forecast-desk` reads `SSH_ORIGINAL_COMMAND` and routes:

| You run                       | You get                                             |
|-------------------------------|-----------------------------------------------------|
| `ssh forecast@box`            | attach-or-create the shared **`desk`** (tmux + TUI) |
| `ssh -t forecast@box desk2`   | an **independent** second TUI (own tmux session)    |
| `ssh forecast@box shell`      | a plain login shell (escape hatch)                  |
| `scp` / `rsync` / `git` / …   | the one-off command runs (escape hatch)             |

**tmux is the default, on purpose:**

1. **Reconnect-resume.** A dropped hotel-wifi link `ssh`es back to the *same*
   desk with scrollback intact — the single most valuable property for a lazy
   operator.
2. **One job runtime.** Each `--tui` spawns its own `tui_gateway` stdio child;
   one shared `desk` session means one runtime, not N.
3. **Mirrored viewing.** Two clients on `desk` (phone + laptop) mirror one
   screen — the right default for one operator on two devices.

### Multi-session semantics (one shared gateway/job runtime)

- `desk`, `desk2`, `desk3` … each `deskN` is an **independent** TUI with its own
  `tui_gateway` job runtime. Safe to run concurrently: the ledger is **WAL-mode**
  (written for exactly the "TUI + cron reforecast" concurrency case), so parallel
  access never corrupts it — but N runtimes duplicate TUI-side polling work.
  Fine occasionally; wasteful as a habit.
- The **nightly cron lives in the gateway process, not the TUI.** It runs whether
  or not anyone is attached. Closing every SSH session does not stop overnight
  forecasting — the systemd-supervised gateway does that.
- The Docker lane lands the same way: `forecast-desk` execs
  `docker exec -it superforecasting-agent-gateway superforecasting-agent --tui`
  inside tmux on the host.

---

## Supervision, volume, backups

- **Supervision.** The native lane installs the packaged systemd unit
  (`superforecasting-agent gateway install --system --run-as-user forecast`),
  which sets `Restart=always` + `WantedBy=multi-user.target`. The Docker lane
  uses `restart: unless-stopped`. Either way: `kill -9` the gateway and it comes
  back; reboot the box and it comes back. **This is load-bearing** — the nightly
  cron is in-process, so if the gateway is down nothing forecasts overnight.
- **Volume.** All state lives under `{home}`
  (`/home/forecast/.superforecasting-agent`, dir `0700`): the SQLite ledger
  (`forecasting/forecasting.db` + `-wal`/`-shm`), `auth.json` (`0600`), `.env`
  (`0600`), `config.yaml`, `identity.json`, `workspace/`, `cron/`, `sessions/`,
  `logs/`, `backups/`. On a real box, mount a Hetzner volume at `{home}` for
  durability independent of the server's lifetime.
- **Backups.** The bootstrap arms a systemd `*.timer` that runs
  `forecast backup run` daily at 07:30 (SQLite online-backup API, 14 daily + 8
  weekly retention, `PRAGMA integrity_check`). Off-box sync (restic/borg/rsync of
  `{home}/backups/`) is the operator's optional extra step.

---

## Upgrades — with a downgrade/migration guard

```bash
ssh root@<ip> 'curl -fsSL \
  https://raw.githubusercontent.com/teddyjfpender/superforecasting-agent/superforecasting-agent-snapshot/scripts/upgrade.sh | bash'
```

`scripts/upgrade.sh` does the safe thing in the safe order:

1. resolve the target **release manifest** (names, checksums, `min_migration_version`);
2. **migration guard BEFORE switching anything** (`scripts/migration_guard.py`):
   - **refuses a downgrade** — installing an older binary over a ledger a newer
     build already forward-migrated;
   - **refuses a build that can't migrate this box** — `current <
     min_migration_version` means you must upgrade through an intermediate
     release first;
   - **unknown current version** → proceeds with a warning + a pre-upgrade
     backup (forward migrations are additive, so this is safe; only a downgrade
     would go undetected);
3. take a **pre-upgrade ledger backup**;
4. install the checksum-verified wheel (pipx lane) / pull the image (Docker lane);
5. restart the supervised gateway;
6. re-stamp the version and run `config doctor` as the post-upgrade gate.

The guard refuses **loudly and changes nothing** on a bad upgrade. `FORCE=1`
overrides it (audited; you own the risk). The installed version is stamped in
`{home}/.release_version`; the manifest's `min_migration_version` is the
machine-readable floor.

---

## Hardening (P3): auth, TLS, spend, observability

The P1 box is already locked down (dedicated user, UFW allow-22-only, zero public
ports). P3 hardens what P1 deployed.

### Gateway HTTP auth — token-gated, same-box UX unchanged

The B4 HTTP+SSE serve mode (`superforecasting-agent --http`) used to trust the
loopback network. It now **mints a bearer token at bootstrap into
`{home}/gateway.token` (`0600`) and REQUIRES it on every route** — `/rpc`,
`/events`, `/status`, and `/health` — with a constant-time compare; a missing or
malformed token gets `401`.

- **Same-box UX is unchanged.** A local client reads the token file
  automatically. The **SSH→TUI landing is unaffected** — it spawns the gateway
  over *stdio*, never HTTP, so the token gates only the HTTP surface.
- **The bind is loopback by default** (`127.0.0.1`). A public bind requires an
  explicit host on `--http` *and* auth; a non-loopback bind with no token and no
  token-file refuses to start (or `--http-gen-token` prints one). Pinned by test
  (`tests/tui_gateway/test_http_server.py`).

The token is a **single shared, operator-grade** secret (not per-user) — it
matches the single-tenant reality below (**one box = one operator**). If you ever
put the dashboard or API server on a public port, they sit behind Caddy's auth
*in addition to* their own tokens.

**`/health` exemption choice (the default is secure).** By default `/health`
requires the token and returns the enriched status. For an external liveness
probe (uptime monitor, dead-man switch), start with `--http-health-public`:
`/health` then answers unauthenticated but returns ONLY the minimal liveness
subset (`status`, `protocol_version`, `version`, `uptime`, `subscribers`) — the
sensitive spend/ledger/cron fields are never served without the token.

### TLS / reverse-proxy — opt-in, because the default is zero-inbound

You only need TLS when you deliberately expose a surface (dashboard, the
OpenAI-compatible API server, Slack Events HTTP mode). Pick by situation:

| Situation | Do this |
|---|---|
| **You (single operator), IP-only box** | **`ssh -L 9119:localhost:9119 forecast@<ip>`** — the honest default. No public port, no cert, nothing to renew. |
| **You, want it always-on from anywhere** | **Tailscale** — a private tailnet address; still no public inbound port. |
| **A domain + a browser-reachable public URL is genuinely required** | **Caddy** (`deploy/caddy/`): `docker compose -f /opt/superforecasting/compose.yml -f deploy/caddy/compose.caddy.yml --profile tls up -d`. Auto-HTTPS via ACME, `basic_auth` in front of the dashboard, SSE buffering off. Open 80+443 only; the dashboard stays loopback-only behind the proxy. |

The `tls` compose profile means **Caddy never starts unless you ask for it** — the
box stays zero-inbound otherwise.

### Unattended spend guards — box-level ceilings

The jobs policy matrix meters LLM spend per job, but nothing capped spend *across*
cycles on an unwatched box. Set **box-level daily/monthly token + USD ceilings**
(`0`/unset = unlimited) in `{home}/.env` (the bootstrap seeds commented guidance;
pass them in the cloud-init env to arm at create time):

```bash
FORECAST_BUDGET_DAILY_USD=10
FORECAST_BUDGET_MONTHLY_USD=150
FORECAST_POLICY_CRON_LLM_SPEND=ask   # require sign-off before any cron spend
```

Enforced at the `authorize(LLM_SPEND)` chokepoint: a breach **refuses further paid
jobs** (a terminal, teaching refusal that names the key to loosen), raises a
`severity=high` ledger alert, and fires a notify event to your connected surfaces.
**Reset is implicit** on the UTC day/month rollover — no cron, no drift.
`forecast config doctor` shows current usage vs each ceiling + headroom.

### Observability — the three curls to run when something feels wrong

The HTTP serve mode exposes a token-gated `/status` (and enriched `/health`) plus
one structured access-log line per request. Start it loopback-only when you want
to poll it: `superforecasting-agent --http 127.0.0.1:8765` (it reuses
`{home}/gateway.token`).

```bash
# 1. Full status: version, uptime, ledger ok, cron last/next-run, active jobs, spend-today.
curl -sS -H "Authorization: Bearer $(cat ~/.superforecasting-agent/gateway.token)" \
     http://127.0.0.1:8765/status | jq

# 2. Liveness only (works unauthenticated iff you started with --http-health-public).
curl -sS -H "Authorization: Bearer $(cat ~/.superforecasting-agent/gateway.token)" \
     http://127.0.0.1:8765/health | jq '{status, uptime, version}'

# 3. The request/boot log — one `http method=… route=… status=… ms=…` line per request.
journalctl -u superforecasting-agent-gateway -n 100 --no-pager   # native lane
docker logs --tail 100 superforecasting-agent-gateway            # docker lane
```

For a remote box, run these over your SSH session, or tunnel with
`ssh -L 8765:localhost:8765 forecast@<ip>` and curl from your laptop.

---

## Verifying the whole chain — the fresh-box proof

`scripts/test-fresh-box.sh` runs the **entire** sequence — bootstrap → services
up → `config doctor` green → SSH-into-TUI — inside a throwaway `ubuntu:24.04`
container with a real `sshd`. It is automated, repeatable, and exits non-zero on
any stage failure:

```bash
scripts/test-fresh-box.sh                 # ubuntu:24.04 (default)
TEST_IMAGE=debian:12 scripts/test-fresh-box.sh
KEEP=1 scripts/test-fresh-box.sh          # leave the container up for triage
```

### Honest real-Hetzner delta — what the container proof cannot cover

| Not covered by the container proof | Where it is verified instead |
|---|---|
| **cloud-init execution** | `deploy/cloud-init.yaml` runs the *same* bootstrap script |
| **systemd boot-time units + `Restart=always` + reboot** | the proof uses `SUPERVISOR=none` (setsid); a real box uses `gateway install --system`, whose generated unit carries `Restart=always` |
| **persistent volumes** | `{home}` is a bind mount in the proof; a real box mounts a Hetzner volume at `{home}` |
| **UFW firewall** (needs kernel netfilter + a daemon) | `SKIP_HARDENING=1` in the proof; the bootstrap runs `ufw allow 22 && ufw enable` on a real box |
| **multi-arch pull from ghcr.io** | CI (`.github/workflows/production-release.yml`) + the local `docker build` proof |

Everything else — `forecast` user creation, pipx install, gateway boot with the
in-process cron banner, `config doctor`, the SSH ForceCommand → tmux → TUI
landing, the escape hatches, reconnect-resume — is exercised for real.

---

## Headless LLM auth (no browser on the box, ever)

All secrets are env / `{home}/.env` / `{home}/auth.json`. Seed OAuth
non-interactively at bootstrap with `AUTH_JSON_BOOTSTRAP`, or authenticate
entirely inside the SSH session afterward:

- `nous` — device-code flow
- `openai-codex` — device flow (`hermes_cli/codex_device_flow.py`)
- browser-bound providers (xai/qwen/gemini) — manual callback-paste over an
  `ssh -L` port-forward (see `website/docs/guides/oauth-over-ssh.md`)

`forecast config doctor` is the gate: it names a missing/typo'd key and its
layer, and reports secrets **presence-only** (never values). The bootstrap runs
it as the acceptance check and refuses to declare success on a red config.

---

## One box = one operator

The agent is **single-tenant by design** (`SECURITY.md` §2): one `{home}`, one
ledger, one `auth.json`, all callers equally trusted. Multiple people =
multiple instances (separate `{home}` + service unit) or separate boxes; or a
Slack/Telegram group surface where teammates talk to the *one* operator's agent
under its allowlists. True multi-tenancy is out of scope.
