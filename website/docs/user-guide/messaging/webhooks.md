---
sidebar_position: 13
title: "Webhooks"
description: "Receive events that trigger forecast reviews and alerts."
---

# Webhooks

Receive events from external services and turn them into forecast review work, evidence alerts, or notifications. The webhook adapter runs an HTTP server that accepts POST requests, validates HMAC signatures, transforms payloads into forecast prompts, and routes review output back to the source or another configured platform.

Use webhooks as alert inputs. They should not silently overwrite active probabilities; the forecast runtime should append evidence, create a review alert, or produce an explicit update that can be audited in the ledger.

## Quick Start

1. Enable via `superforecasting-agent gateway setup` or environment variables
2. Define routes in `config.yaml` **or** create them dynamically with `superforecasting-agent webhook subscribe`
3. Point your service at `http://your-server:8644/webhooks/<route-name>`

---

## Setup

There are two ways to enable the webhook adapter.

### Via setup wizard

```bash
superforecasting-agent gateway setup
```

Follow the prompts to enable webhooks, set the port, and set a global HMAC secret.

### Via environment variables

Add to `~/.superforecasting-agent/.env`:

```bash
WEBHOOK_ENABLED=true
WEBHOOK_PORT=8644        # default
WEBHOOK_SECRET=your-global-secret
```

### Verify the server

Once the gateway is running:

```bash
curl http://localhost:8644/health
```

Expected response:

```json
{"status": "ok", "platform": "webhook"}
```

---

## Configuring Routes {#configuring-routes}

Routes define how different webhook sources are handled. Each route is a named entry under `platforms.webhook.extra.routes` in your `config.yaml`.

### Route properties

| Property | Required | Description |
|----------|----------|-------------|
| `events` | No | List of event types to accept (e.g. `["issues"]`). If empty, all events are accepted. Event type is read from `X-GitHub-Event`, `X-GitLab-Event`, or `event_type` in the payload. |
| `secret` | **Yes** | HMAC secret for signature validation. Falls back to the global `secret` if not set on the route. Set to `"INSECURE_NO_AUTH"` for testing only (skips validation). |
| `prompt` | No | Template string with dot-notation payload access (e.g. `{issue.title}`). If omitted, the full JSON payload is dumped into the prompt. |
| `skills` | No | List of skill names to load for the forecast review. |
| `deliver` | No | Where to send the response: `github_comment`, `telegram`, `discord`, `slack`, `signal`, `sms`, `whatsapp`, `matrix`, `mattermost`, `email`, `dingtalk`, `feishu`, `wecom`, `weixin`, `bluebubbles`, `qqbot`, or `log` (default). |
| `deliver_extra` | No | Additional delivery config — keys depend on `deliver` type (e.g. `repo`, `pr_number`, `chat_id`). Values support the same `{dot.notation}` templates as `prompt`. |
| `deliver_only` | No | If `true`, skip forecast review entirely — the rendered `prompt` template becomes the literal message that gets delivered. Zero LLM cost, sub-second delivery. See [Direct Delivery Mode](#direct-delivery-mode) for use cases. Requires `deliver` to be a real target (not `log`). |

### Full example

```yaml
platforms:
  webhook:
    enabled: true
    extra:
      port: 8644
      secret: "global-fallback-secret"
      routes:
        forecast-evidence:
          events: ["issues"]
          secret: "github-webhook-secret"
          prompt: |
            Review this new evidence candidate for active forecasts:
            Repository: {repository.full_name}
            Issue #{issue.number}: {issue.title}
            Reporter: {issue.user.login}
            URL: {issue.html_url}
            Action: {action}
          skills: ["forecast-review"]
          deliver: "github_comment"
          deliver_extra:
            repo: "{repository.full_name}"
            pr_number: "{issue.number}"
        market-alert:
          events: ["push"]
          secret: "market-feed-secret"
          prompt: "Potential evidence update for forecast portfolio: {head_commit.message}"
          deliver: "telegram"
```

### Prompt Templates

Prompts use dot-notation to access nested fields in the webhook payload:

- `{issue.title}` resolves to `payload["issue"]["title"]`
- `{repository.full_name}` resolves to `payload["repository"]["full_name"]`
- `{__raw__}` — special token that dumps the **entire payload** as indented JSON (truncated at 4000 characters). Useful for monitoring alerts or generic webhooks where the forecast runtime needs the full context.
- Missing keys are left as the literal `{key}` string (no error)
- Nested dicts and lists are JSON-serialized and truncated at 2000 characters

You can mix `{__raw__}` with regular template variables:

```yaml
prompt: "Evidence alert #{issue.number} by {issue.user.login}: {__raw__}"
```

If no `prompt` template is configured for a route, the entire payload is dumped as indented JSON (truncated at 4000 characters).

The same dot-notation templates work in `deliver_extra` values.

### Forum Topic Delivery

When delivering webhook responses to Telegram, you can target a specific forum topic by including `message_thread_id` (or `thread_id`) in `deliver_extra`:

```yaml
webhooks:
  routes:
    alerts:
      events: ["alert"]
      prompt: "Alert: {__raw__}"
      deliver: "telegram"
      deliver_extra:
        chat_id: "-1001234567890"
        message_thread_id: "42"
```

If `chat_id` is not provided in `deliver_extra`, the delivery falls back to the home channel configured for the target platform.

---

## GitHub Evidence Review (Step by Step) {#github-pr-review}

This walkthrough sets up a GitHub issue webhook that turns tagged evidence notes into forecast review work. Keep the old anchor so existing links still resolve.

### 1. Create the webhook in GitHub

1. Go to your repository → **Settings** → **Webhooks** → **Add webhook**
2. Set **Payload URL** to `http://your-server:8644/webhooks/forecast-evidence`
3. Set **Content type** to `application/json`
4. Set **Secret** to match your route config (e.g. `github-webhook-secret`)
5. Under **Which events?**, select **Let me select individual events** and check **Issues**
6. Click **Add webhook**

### 2. Add the route config

Add the `forecast-evidence` route to your `~/.superforecasting-agent/config.yaml` as shown in the example above.

### 3. Ensure `gh` CLI is authenticated

The `github_comment` delivery type uses the GitHub CLI to post comments:

```bash
gh auth login
```

### 4. Test it

Open an issue that contains a possible source, market move, model input, or resolution update. The webhook fires, the forecast runtime reviews the event, and posts a comment with the review result.

---

## GitLab Webhook Setup {#gitlab-webhook-setup}

GitLab webhooks work similarly but use a different authentication mechanism. GitLab sends the secret as a plain `X-Gitlab-Token` header (exact string match, not HMAC).

### 1. Create the webhook in GitLab

1. Go to your project → **Settings** → **Webhooks**
2. Set the **URL** to `http://your-server:8644/webhooks/gitlab-mr`
3. Enter your **Secret token**
4. Select **Merge request events** (and any other events you want)
5. Click **Add webhook**

### 2. Add the route config

```yaml
platforms:
  webhook:
    enabled: true
    extra:
      routes:
        gitlab-mr:
          events: ["merge_request"]
          secret: "your-gitlab-secret-token"
          prompt: |
            Review this merge request as possible evidence:
            Project: {project.path_with_namespace}
            MR !{object_attributes.iid}: {object_attributes.title}
            Author: {object_attributes.last_commit.author.name}
            URL: {object_attributes.url}
            Action: {object_attributes.action}
          deliver: "log"
```

---

## Delivery Options {#delivery-options}

The `deliver` field controls where the forecast review output goes after processing the webhook event.

| Deliver Type | Description |
|-------------|-------------|
| `log` | Logs the response to the gateway log output. This is the default and is useful for testing. |
| `github_comment` | Posts the response as a PR/issue comment via the `gh` CLI. Requires `deliver_extra.repo` and `deliver_extra.pr_number`. The `gh` CLI must be installed and authenticated on the gateway host (`gh auth login`). |
| `telegram` | Routes the response to Telegram. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `discord` | Routes the response to Discord. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `slack` | Routes the response to Slack. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `signal` | Routes the response to Signal. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `sms` | Routes the response to SMS via Twilio. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `whatsapp` | Routes the response to WhatsApp. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `matrix` | Routes the response to Matrix. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `mattermost` | Routes the response to Mattermost. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `email` | Routes the response to Email. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `dingtalk` | Routes the response to DingTalk. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `feishu` | Routes the response to Feishu/Lark. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `wecom` | Routes the response to WeCom. Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `weixin` | Routes the response to Weixin (WeChat). Uses the home channel, or specify `chat_id` in `deliver_extra`. |
| `bluebubbles` | Routes the response to BlueBubbles (iMessage). Uses the home channel, or specify `chat_id` in `deliver_extra`. |

For cross-platform delivery, the target platform must also be enabled and connected in the gateway. If no `chat_id` is provided in `deliver_extra`, the response is sent to that platform's configured home channel.

---

## Direct Delivery Mode {#direct-delivery-mode}

By default, every webhook POST triggers a forecast-runtime review: the payload becomes a prompt, the runtime processes it, and the review output is delivered. This costs LLM tokens on every event.

For use cases where you just want to **push a plain notification** — no reasoning, no review loop, just deliver the message — set `deliver_only: true` on the route. The rendered `prompt` template becomes the literal message body, and the adapter dispatches it directly to the configured delivery target.

### When to use direct delivery

- **Evidence-source push** — internal data feed changes → notify a forecaster in Telegram instantly
- **Monitoring alerts** — Datadog/Grafana alert webhook → push to a Discord channel for review
- **Benchmark completion** — backtest job finishes → post performance summary to Slack
- **Resolution notices** — upstream service marks a question resolved → alert the forecast book owner

Benefits:

- **Zero LLM tokens** — no forecast review is invoked
- **Sub-second delivery** — a single adapter call, no reasoning loop
- **Same security as review mode** — HMAC auth, rate limits, idempotency, and body-size limits all still apply
- **Synchronous response** — the POST returns `200 OK` once delivery succeeds, or `502` if the target rejects it, so your upstream service can retry intelligently

### Example: Telegram push from a data feed

```yaml
platforms:
  webhook:
    enabled: true
    extra:
      port: 8644
      secret: "global-secret"
      routes:
        rate-alert:
          secret: "rates-feed-secret"
          deliver: "telegram"
          deliver_only: true
          prompt: "New CPI observation available: {observation.date} {observation.value}"
          deliver_extra:
            chat_id: "{forecast.telegram_chat_id}"
```

Your feed publisher signs the payload with HMAC-SHA256 and POSTs to `https://your-server:8644/webhooks/rate-alert`. The webhook adapter validates the signature, renders the template from the payload, delivers to Telegram, and returns `200 OK`.

### Example: Dynamic subscription via CLI

```bash
superforecasting-agent webhook subscribe rate-alert \
  --deliver telegram \
  --deliver-chat-id "123456789" \
  --deliver-only \
  --prompt "New CPI observation available: {observation.date} {observation.value}" \
  --description "CPI evidence notifications"
```

### Response codes

| Status | Meaning |
|--------|---------|
| `200 OK` | Delivered successfully. Body: `{"status": "delivered", "route": "...", "target": "...", "delivery_id": "..."}` |
| `200 OK` (status=duplicate) | Duplicate `X-GitHub-Delivery` ID within the idempotency TTL (1 hour). Not re-delivered. |
| `401 Unauthorized` | HMAC signature invalid or missing. |
| `400 Bad Request` | Malformed JSON body. |
| `404 Not Found` | Unknown route name. |
| `413 Payload Too Large` | Body exceeded `max_body_bytes`. |
| `429 Too Many Requests` | Route rate limit exceeded. |
| `502 Bad Gateway` | Target adapter rejected the message or raised. The error is logged server-side; the response body is a generic `Delivery failed` to avoid leaking adapter internals. |

### Configuration gotchas

- `deliver_only: true` requires `deliver` to be a real target. `deliver: log` (or omitting `deliver`) is rejected at startup — the adapter refuses to start if it finds a misconfigured route.
- The `skills` field is ignored in direct delivery mode because no forecast review runs.
- Template rendering uses the same `{dot.notation}` syntax as review mode, including the `{__raw__}` token.
- Idempotency uses the same `X-GitHub-Delivery` / `X-Request-ID` header — retries with the same ID return `status=duplicate` and do NOT re-deliver.

---

## Dynamic Subscriptions (CLI) {#dynamic-subscriptions}

In addition to static routes in `config.yaml`, you can create webhook subscriptions dynamically using the `superforecasting-agent webhook` CLI command. This is useful when a forecast workflow needs to set up event-driven evidence triggers.

### Create a subscription

```bash
superforecasting-agent webhook subscribe github-issues \
  --events "issues" \
  --prompt "Possible evidence for active forecasts: issue #{issue.number}: {issue.title}\nBy: {issue.user.login}\n\n{issue.body}" \
  --deliver telegram \
  --deliver-chat-id "-100123456789" \
  --description "Review new GitHub evidence notes"
```

This returns the webhook URL and an auto-generated HMAC secret. Configure your service to POST to that URL.

### List subscriptions

```bash
superforecasting-agent webhook list
```

### Remove a subscription

```bash
superforecasting-agent webhook remove github-issues
```

### Test a subscription

```bash
superforecasting-agent webhook test github-issues
superforecasting-agent webhook test github-issues --payload '{"issue": {"number": 42, "title": "Test"}}'
```

### How dynamic subscriptions work

- Subscriptions are stored in `~/.superforecasting-agent/webhook_subscriptions.json`
- The webhook adapter hot-reloads this file on each incoming request (mtime-gated, negligible overhead)
- Static routes from `config.yaml` always take precedence over dynamic ones with the same name
- Dynamic subscriptions use the same route format and capabilities as static routes (events, prompt templates, skills, delivery)
- No gateway restart required — subscribe and it's immediately live

### Workflow-driven subscriptions

The runtime can create subscriptions via the terminal tool when guided by the `webhook-subscriptions` skill. Ask it to "set up a webhook for forecast evidence notes" and it will run the appropriate `superforecasting-agent webhook subscribe` command.

---

## Security {#security}

The webhook adapter includes multiple layers of security:

### HMAC signature validation

The adapter validates incoming webhook signatures using the appropriate method for each source:

- **GitHub**: `X-Hub-Signature-256` header — HMAC-SHA256 hex digest prefixed with `sha256=`
- **GitLab**: `X-Gitlab-Token` header — plain secret string match
- **Generic**: `X-Webhook-Signature` header — raw HMAC-SHA256 hex digest

If a secret is configured but no recognized signature header is present, the request is rejected.

### Secret is required

Every route must have a secret — either set directly on the route or inherited from the global `secret`. Routes without a secret cause the adapter to fail at startup with an error. For development/testing only, you can set the secret to `"INSECURE_NO_AUTH"` to skip validation entirely.

`INSECURE_NO_AUTH` is only accepted when the gateway is bound to a loopback host (`127.0.0.1`, `localhost`, `::1`). If it is combined with a non-loopback bind such as `0.0.0.0` or a LAN IP, the adapter refuses to start — this prevents accidentally exposing an unauthenticated endpoint on a public interface.

### Rate limiting

Each route is rate-limited to **30 requests per minute** by default (fixed-window). Configure this globally:

```yaml
platforms:
  webhook:
    extra:
      rate_limit: 60  # requests per minute
```

Requests exceeding the limit receive a `429 Too Many Requests` response.

### Idempotency

Delivery IDs (from `X-GitHub-Delivery`, `X-Request-ID`, or a timestamp fallback) are cached for **1 hour**. Duplicate deliveries are silently skipped with a `200` response, preventing duplicate review runs.

### Body size limits

Payloads exceeding **1 MB** are rejected before the body is read. Configure this:

```yaml
platforms:
  webhook:
    extra:
      max_body_bytes: 2097152  # 2 MB
```

### Prompt injection risk

:::warning
Webhook payloads contain attacker-controlled data — PR titles, commit messages, issue descriptions, etc. can all contain malicious instructions. Run the gateway in a sandboxed environment (Docker, VM) when exposed to the internet. Consider using the Docker or SSH terminal backend for isolation.
:::

---

## Troubleshooting {#troubleshooting}

### Webhook not arriving

- Verify the port is exposed and accessible from the webhook source
- Check firewall rules — port `8644` (or your configured port) must be open
- Verify the URL path matches: `http://your-server:8644/webhooks/<route-name>`
- Use the `/health` endpoint to confirm the server is running

### Signature validation failing

- Ensure the secret in your route config exactly matches the secret configured in the webhook source
- For GitHub, the secret is HMAC-based — check `X-Hub-Signature-256`
- For GitLab, the secret is a plain token match — check `X-Gitlab-Token`
- Check gateway logs for `Invalid signature` warnings

### Event being ignored

- Check that the event type is in your route's `events` list
- GitHub events use values like `pull_request`, `push`, `issues` (the `X-GitHub-Event` header value)
- GitLab events use values like `merge_request`, `push` (the `X-GitLab-Event` header value)
- If `events` is empty or not set, all events are accepted

### Forecast review not responding

- Run the gateway in foreground to see logs: `superforecasting-agent gateway run`
- Check that the prompt template is rendering correctly
- Verify the delivery target is configured and connected

### Duplicate responses

- The idempotency cache should prevent this — check that the webhook source is sending a delivery ID header (`X-GitHub-Delivery` or `X-Request-ID`)
- Delivery IDs are cached for 1 hour

### `gh` CLI errors (GitHub comment delivery)

- Run `gh auth login` on the gateway host
- Ensure the authenticated GitHub user has write access to the repository
- Check that `gh` is installed and on the PATH

---

## Environment Variables {#environment-variables}

| Variable | Description | Default |
|----------|-------------|---------|
| `WEBHOOK_ENABLED` | Enable the webhook platform adapter | `false` |
| `WEBHOOK_PORT` | HTTP server port for receiving webhooks | `8644` |
| `WEBHOOK_SECRET` | Global HMAC secret (used as fallback when routes don't specify their own) | _(none)_ |
