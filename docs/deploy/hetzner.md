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
  https://raw.githubusercontent.com/teddyjfpender/superforecasting-agent/main/scripts/hetzner-install.sh \
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
  https://raw.githubusercontent.com/teddyjfpender/superforecasting-agent/main/scripts/upgrade.sh | bash'
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
