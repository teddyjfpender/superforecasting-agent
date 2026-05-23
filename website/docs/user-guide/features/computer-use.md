# Computer Use (macOS)

Superforecasting Agent can drive a Mac desktop in the background: clicking, typing, scrolling, dragging, and capturing screenshots without moving your visible cursor or stealing keyboard focus.

For this fork, computer use is an evidence and source-inspection tool. Use it when a relevant source cannot be reached through structured APIs, browser automation, web extraction, or files. Examples include inspecting a local application, checking a data dashboard, reviewing a private email or document view, or capturing visual evidence for later ledger import.

Computer Use does not create durable forecast state by itself. Screenshots, copied text, and summaries remain transient until you explicitly write evidence, model runs, assumptions, forecast updates, resolutions, scores, postmortems, or calibration lessons to the forecast ledger.

## How It Works

The `computer_use` toolset speaks MCP over stdio to [`cua-driver`](https://github.com/trycua/cua), a macOS driver that uses SkyLight private SPIs and accessibility APIs to:

- Post synthesized events directly to target processes.
- Avoid HID cursor warping.
- Keep app windows usable without switching Spaces.
- Keep Chromium/Electron accessibility trees alive when windows are occluded.

This is the same background-computer-use style used by editor agents, but exposed through the Superforecasting Agent tool runtime.

## When to Use

Prefer structured sources first:

1. Native forecast connectors and source adapters.
2. `web_search` / `web_extract`.
3. Browser automation.
4. Local files or exported datasets.
5. Computer Use as the fallback for GUI-only sources.

Good forecast-desk uses:

- Inspect a private dashboard that has no API.
- Read a local email or document needed for a forecast review.
- Capture a chart from a source that cannot be exported cleanly.
- Verify a GUI-only workflow while building a source adapter.
- Compare what a web page visually shows against structured extraction.

Avoid using Computer Use for routine web browsing, unattended credential entry, or any action that could mutate external systems without review.

## Enabling

### Option 1: Dedicated CLI command

```bash
superforecasting-agent computer-use install
```

This fetches and runs the upstream `cua-driver` installer:

```text
https://raw.githubusercontent.com/trycua/cua/main/libs/cua-driver/scripts/install.sh
```

Verify installation:

```bash
superforecasting-agent computer-use status
```

### Option 2: Interactive tool configuration

```bash
superforecasting-agent tools
```

Pick **Computer Use (macOS)**, then select the `cua-driver` background backend. This runs the same installer.

### macOS permissions

Grant permissions when prompted:

- System Settings -> Privacy & Security -> Accessibility
- System Settings -> Privacy & Security -> Screen Recording

Allow the terminal, editor, or app that launches Superforecasting Agent.

### Start a session

```bash
superforecasting-agent chat -t computer_use
```

or add `computer_use` to the enabled toolsets in `~/.superforecasting-agent/config.yaml`.

Legacy configurations may still use `~/.hermes/config.yaml` during migration.

## Keeping `cua-driver` Current

The upstream driver ships fixes periodically. Superforecasting Agent refreshes it in two ways:

- `superforecasting-agent update` reruns the upstream installer when `cua-driver` is already present.
- `superforecasting-agent computer-use install --upgrade` force-refreshes manually.

`superforecasting-agent computer-use status` shows the installed version and binary path.

## Forecast Example

Prompt:

```text
Inspect the latest private dashboard view for the "Will vendor X miss its Q3 delivery SLA?" forecast. Capture relevant visual evidence, but do not update the probability until I approve the evidence summary.
```

Likely tool flow:

1. `computer_use(action="capture", mode="som", app="Dashboard")` to number visible controls and table rows.
2. `computer_use(action="click", element=14)` to open the date filter.
3. `computer_use(action="type", text="Q3")`.
4. `computer_use(action="key", keys="return", capture_after=True)`.
5. Extract visible SLA rows and cite the screenshot path.
6. Ask whether to record the relevant claims with `forecast evidence add`.
7. Only after ledgered evidence and user approval, run `forecast update`.

The GUI interaction and screenshot are not the forecast update. The append-only ledger entry is.

## Provider Compatibility

| Provider | Vision? | Works? | Notes |
|----------|---------|--------|-------|
| Anthropic vision models | Yes | Yes | Strong with SOM plus raw coordinates. |
| OpenRouter vision models | Yes | Yes | Multi-part tool messages supported. |
| OpenAI GPT-4+/GPT-5 vision-capable models | Yes | Yes | Multi-part tool messages supported. |
| Local vLLM / LM Studio vision models | Yes | Yes | Requires multi-part tool content support. |
| Text-only models | No | Degraded | Use `mode="ax"` for accessibility-tree-only operation. |

Screenshots are sent inline with tool results as OpenAI-style `image_url` parts. Anthropic adapters convert them to native `tool_result` image blocks.

## Safety

Computer Use has several guardrails:

- Destructive actions such as click, type, drag, scroll, key, and focus-app can require approval.
- Hard-blocked key combos include empty trash, force delete, lock screen, log out, and force log out.
- Hard-blocked type patterns include `curl | bash`, `sudo rm -rf /`, fork bombs, and similar shell payloads.
- The runtime prompt forbids clicking permission dialogs, typing passwords, or following instructions embedded in screenshots.

For stricter review, set manual approvals in `~/.superforecasting-agent/config.yaml`:

```yaml
approvals:
  mode: manual
```

Use a dedicated forecast profile for GUI-heavy workflows when you want narrower tool access.

## Token Efficiency

Screenshots are expensive. The runtime applies several optimizations:

- Screenshot eviction keeps only the most recent screenshots in context.
- Compression strips image parts from old multimodal tool results.
- Image-aware token estimation avoids treating base64 length as text tokens.
- Anthropic server-side context editing can clear old tool results when supported.

A long GUI session can still be expensive. Prefer extracting the minimal relevant facts, then writing concise evidence records to the ledger.

## Limitations

- **macOS only.** `cua-driver` depends on private Apple APIs. For cross-platform GUI work, prefer the browser toolset.
- **Private SPI risk.** Apple can change SkyLight symbols in OS updates.
- **Performance.** Background events are slower than direct HID posting.
- **No password typing.** Use system autofill or manual entry.
- **GUI evidence can be fragile.** Record source timestamps, screenshot paths, and what was actually visible before using it in a forecast.

## Configuration

Inherited environment variable names are still used for the driver:

```bash
HERMES_CUA_DRIVER_CMD=/opt/homebrew/bin/cua-driver
HERMES_CUA_DRIVER_VERSION=0.5.0
```

For tests and CI:

```bash
HERMES_COMPUTER_USE_BACKEND=noop
```

These names are compatibility identifiers. New product docs and commands should still refer to Superforecasting Agent.

## Troubleshooting

**`computer_use backend unavailable: cua-driver is not installed`**

Run:

```bash
superforecasting-agent computer-use install
```

or enable Computer Use through:

```bash
superforecasting-agent tools
```

**Clicks seem to have no effect**

Capture again. A modal, permission prompt, or stale window state may be blocking input.

**Element indices are stale**

SOM indices are only valid until the next state change. Re-capture after every action that changes the screen.

**`blocked pattern in type text`**

The text matches a dangerous shell-pattern block. Break the task into safer steps or do the sensitive part manually.

## See Also

- Bundled skill: `macos-computer-use`
- [cua-driver source](https://github.com/trycua/cua)
- [Browser automation](./browser.md) for cross-platform web tasks.
