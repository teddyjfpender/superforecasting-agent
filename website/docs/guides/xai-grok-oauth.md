---
sidebar_position: 16
title: "xAI Grok OAuth (SuperGrok / X Premium+)"
description: "Sign in with SuperGrok or X Premium+ to use Grok models in the forecast runtime"
---

# xAI Grok OAuth (SuperGrok / X Premium+)

Superforecasting Agent supports xAI Grok through a browser-based OAuth login flow against [accounts.x.ai](https://accounts.x.ai), using either a **SuperGrok subscription** ([grok.com](https://x.ai/grok)) or an **X Premium+ subscription** (linked X account). No `XAI_API_KEY` is required — log in once and the forecast runtime automatically refreshes your session in the background.

When you sign in with an X account that has Premium+, xAI automatically links the subscription status to your xAI session, so the OAuth flow works the same as it does for direct SuperGrok subscribers.

The transport reuses the `codex_responses` adapter (xAI exposes a Responses-style endpoint), so reasoning, tool-calling, streaming, and prompt caching work without any adapter changes.

The same OAuth bearer token is also reused by every direct-to-xAI surface in Superforecasting Agent — TTS, image generation, video generation, and transcription — so a single login covers the auxiliary media and search tools used during research.

## Overview

| Item | Value |
|------|-------|
| Provider ID | `xai-oauth` |
| Display name | xAI Grok OAuth (SuperGrok / X Premium+) |
| Auth type | Browser OAuth 2.0 PKCE (loopback callback) |
| Transport | xAI Responses API (`codex_responses`) |
| Default model | `grok-4.3` |
| Endpoint | `https://api.x.ai/v1` |
| Auth server | `https://accounts.x.ai` |
| Requires env var | No (`XAI_API_KEY` is **not** used for this provider) |
| Subscription | [SuperGrok](https://x.ai/grok) or [X Premium+](https://x.com/i/premium_sign_up) — see note below |

## Forecast Runtime Notes

Use this provider as one inference source inside the forecasting desk, not as the final probability authority by itself. Forecast records should persist the provider id, model name, credential mode, prompt version, and run timestamp so backtests can compare Grok-assisted forecasts against other models, market priors, and calibrated ensembles.

## Prerequisites

- Python 3.9+
- Superforecasting Agent installed
- An active **SuperGrok** subscription on your xAI account, **or** an **X Premium+** subscription on the X account you sign in with (xAI links the subscription automatically)
- A browser available on the local machine (or use `--no-browser` for remote sessions)

:::warning xAI may restrict OAuth API access by tier
xAI's backend enforces its own allowlist on the OAuth API surface and has been seen to reject standard SuperGrok subscribers with `HTTP 403` (upstream compatibility issue `#26847`) even though the in-app subscription is active. If OAuth login succeeds in the browser but inference returns 403, set `XAI_API_KEY` and switch to the API-key path (`provider: xai`) — that surface is not subject to the same gating today.
:::

## Quick Start

```bash
# Launch the provider and model picker
superforecasting-agent model
# → Select "xAI Grok OAuth (SuperGrok / X Premium+)" from the provider list
# → Superforecasting Agent opens your browser to accounts.x.ai
# → Approve access in the browser
# → Pick a model (grok-4.3 is at the top)
# → Start forecasting

superforecasting-agent
```

After the first login, credentials are stored under `~/.superforecasting-agent/auth.json` and refreshed automatically before they expire.

## Logging In Manually

You can trigger a login without going through the model picker:

```bash
superforecasting-agent auth add xai-oauth
```

### Remote / headless sessions

On servers, containers, or SSH sessions where no browser is available, Superforecasting Agent detects the remote environment and prints the authorization URL instead of opening a browser.

**Important:** the loopback listener still runs on the remote machine at `127.0.0.1:56121`. The xAI redirect needs to reach *that* listener, so opening the URL on your laptop will fail (`Could not establish connection. We couldn't reach your app.`) unless you forward the port:

```bash
# In a separate terminal on your local machine:
ssh -N -L 56121:127.0.0.1:56121 user@remote-host

# Then in your SSH session on the remote machine:
superforecasting-agent auth add xai-oauth --no-browser
# Open the printed authorize URL in your local browser.
```

Through a jump box / bastion: add `-J jump-user@jump-host`.

See [OAuth over SSH / Remote Hosts](./oauth-over-ssh.md) for the full step-by-step, including ProxyJump chains, mosh/tmux, and ControlMaster gotchas.

### Browser-only remotes (Cloud Shell, Codespaces, EC2 Instance Connect)

If you don't have a regular SSH client (e.g. you're running Superforecasting Agent inside GCP Cloud Shell, GitHub Codespaces, AWS EC2 Instance Connect, Gitpod, or another browser-based console), the `ssh -L` recipe above isn't available. Use `--manual-paste` instead — Superforecasting Agent skips the loopback listener and lets you paste the failed callback URL straight from your browser:

```bash
superforecasting-agent auth add xai-oauth --manual-paste
# Or via the model picker:
superforecasting-agent model --manual-paste
```

See [OAuth over SSH / Remote Hosts](./oauth-over-ssh.md#browser-only-remote-cloud-shell--codespaces--ec2-instance-connect) for the full walkthrough. Regression fix for upstream compatibility issue `#26923`.

## How the Login Works

1. Superforecasting Agent opens your browser to `accounts.x.ai`.
2. You sign in (or confirm your existing session) and approve access.
3. xAI redirects back to Superforecasting Agent and the tokens are saved to `~/.superforecasting-agent/auth.json`.
4. From then on, Superforecasting Agent refreshes the access token in the background — you stay signed in until you `superforecasting-agent auth remove xai-oauth` or revoke access from your xAI account settings.

## Checking Login Status

```bash
superforecasting-agent doctor
```

The `◆ Auth Providers` section will show the current state of every provider, including `xai-oauth`.

## Switching Models

```bash
superforecasting-agent model
# → Select "xAI Grok OAuth (SuperGrok / X Premium+)"
# → Pick from the model list (grok-4.3 is pinned to the top)
```

Or set the model directly:

```bash
superforecasting-agent config set model.default grok-4.3
superforecasting-agent config set model.provider xai-oauth
```

## Configuration Reference

After login, `~/.superforecasting-agent/config.yaml` will contain:

```yaml
model:
  default: grok-4.3
  provider: xai-oauth
  base_url: https://api.x.ai/v1
```

### Provider aliases

All of the following resolve to `xai-oauth`:

```bash
superforecasting-agent --provider xai-oauth        # canonical
superforecasting-agent --provider grok-oauth       # alias
superforecasting-agent --provider x-ai-oauth       # alias
superforecasting-agent --provider xai-grok-oauth   # alias
```

## Direct-to-xAI Tools (TTS / Image / Video / Transcription / X Search)

Once you're logged in via OAuth, every direct-to-xAI tool reuses the same bearer token automatically — there is **no separate setup** unless you'd rather use an API key.

To pick a backend for each tool:

```bash
superforecasting-agent tools
# → Text-to-Speech       → "xAI TTS"
# → Image Generation     → "xAI Grok Imagine (image)"
# → Video Generation     → "xAI Grok Imagine"
# → X (Twitter) Search   → "xAI Grok OAuth (SuperGrok / X Premium+)"
```

If OAuth tokens are already stored, the picker confirms it and skips the credential prompt. If neither OAuth nor `XAI_API_KEY` is set, the picker offers a 3-choice menu: OAuth login, paste API key, or skip.

:::note Video generation is off by default
The `video_gen` toolset is disabled by default. Enable it in `superforecasting-agent tools` → `🎬 Video Generation` (press space) before the agent can call `video_generate`. Otherwise the agent may fall back to the bundled ComfyUI skill, which is also tagged for video generation.
:::

:::note X search auto-enables when xAI credentials are present
The `x_search` toolset auto-enables whenever xAI credentials (a SuperGrok / X Premium+ OAuth token or `XAI_API_KEY`) are configured. Disable explicitly via `superforecasting-agent tools` → `🐦 X (Twitter) Search` (press space) if you don't want this. The tool routes through xAI's built-in `x_search` Responses API — it works with **either** your SuperGrok / X Premium+ OAuth login or a paid `XAI_API_KEY`, and prefers OAuth when both are configured (uses your subscription quota instead of API spend). The tool schema is hidden from the model when no xAI credentials are configured, regardless of whether the toolset is enabled.
:::

### Models

| Tool | Model | Notes |
|------|-------|-------|
| Chat | `grok-4.3` | Default; auto-selected when you log in via OAuth |
| Chat | `grok-4.20-0309-reasoning` | Reasoning variant |
| Chat | `grok-4.20-0309-non-reasoning` | Non-reasoning variant |
| Chat | `grok-4.20-multi-agent-0309` | Multi-agent variant |
| Image | `grok-imagine-image` | Default; ~5–10 s |
| Image | `grok-imagine-image-quality` | Higher fidelity; ~10–20 s |
| Video | `grok-imagine-video` | Text-to-video and image-to-video; up to 7 reference images |
| TTS | (default voice) | xAI `/v1/tts` endpoint |

The chat catalog is derived live from the on-disk `models.dev` cache; new xAI releases appear automatically once that cache refreshes. `grok-4.3` is always pinned to the top of the list.

## Environment Variables

| Variable | Effect |
|----------|--------|
| `XAI_BASE_URL` | Override the default `https://api.x.ai/v1` endpoint (rarely needed). |

To force this provider for a single run, pass the provider flag instead:

```bash
superforecasting-agent --provider xai-oauth
```

## Troubleshooting

### Token expired — not re-logging in automatically

Superforecasting Agent refreshes the token before each session and again reactively on a 401. If refresh fails with `invalid_grant` (the refresh token was revoked, or the account was rotated), Superforecasting Agent surfaces a typed re-auth message instead of crashing.

When the refresh failure is terminal (HTTP 4xx, `invalid_grant`, revoked grant, etc.), Superforecasting Agent marks the refresh token as dead and quarantines it locally — subsequent calls skip the doomed refresh attempt instead of replaying the same 401 over and over. The agent surfaces a single "re-authentication required" message and stays out of the way until you log in again.

**Fix:** run `superforecasting-agent auth add xai-oauth` again to start a fresh login. The quarantine clears on the next successful exchange.

### Authorization timed out

The loopback listener has a finite expiry window (default 180 s). If you don't approve the login in time, Superforecasting Agent raises a timeout error.

**Fix:** re-run `superforecasting-agent auth add xai-oauth` (or `superforecasting-agent model`). The flow starts fresh.

### State mismatch (possible CSRF)

Superforecasting Agent detected that the `state` value returned by the authorization server doesn't match what it sent.

**Fix:** re-run the login. If it persists, check for a proxy or redirect that is modifying the OAuth response.

### Logging in from a remote server

On SSH or container sessions Superforecasting Agent prints the authorization URL instead of opening a browser. The loopback callback listener still binds `127.0.0.1:56121` on the remote host — your laptop's browser can't reach it without an SSH local-forward:

```bash
# Local machine, separate terminal:
ssh -N -L 56121:127.0.0.1:56121 user@remote-host

# Remote machine:
superforecasting-agent auth add xai-oauth --no-browser
```

Full walkthrough (jump boxes, mosh/tmux, port conflicts): [OAuth over SSH / Remote Hosts](./oauth-over-ssh.md).

### HTTP 403 after a successful login (tier / entitlement)

OAuth completed in the browser, tokens are saved, but inference or token refresh returns `HTTP 403` with a message similar to *"The caller does not have permission to execute the specified operation"*.

This is **not** a stale-token problem — re-running `superforecasting-agent model` won't change it. xAI's backend has been seen to restrict OAuth API access to specific SuperGrok tiers despite the in-app subscription being active (upstream compatibility issue `#26847`).

**Fix:** set `XAI_API_KEY` and switch to the API-key path:

```bash
export XAI_API_KEY=xai-...
superforecasting-agent config set model.provider xai
```

Or upgrade your subscription at [x.ai/grok](https://x.ai/grok) if the OAuth route is required.

### "No xAI credentials found" error at runtime

The auth store has no `xai-oauth` entry and no `XAI_API_KEY` is set. You haven't logged in yet, or the credential file was deleted.

**Fix:** run `superforecasting-agent model` and pick the xAI Grok OAuth provider, or run `superforecasting-agent auth add xai-oauth`.

## Logging Out

To remove all stored xAI Grok OAuth credentials:

```bash
superforecasting-agent auth logout xai-oauth
```

This clears both the singleton OAuth entry in `auth.json` and any credential-pool rows for `xai-oauth`. Use `superforecasting-agent auth remove xai-oauth <index|id|label>` if you only want to drop a single pool entry (run `superforecasting-agent auth list xai-oauth` to see them).

## See Also

- [OAuth over SSH / Remote Hosts](./oauth-over-ssh.md) — required reading if Superforecasting Agent is on a different machine than your browser
- [AI Providers reference](../integrations/providers.md)
- [Environment Variables](../reference/environment-variables.md)
- [Configuration](../user-guide/configuration.md)
- [Voice & TTS](../user-guide/features/tts.md)
