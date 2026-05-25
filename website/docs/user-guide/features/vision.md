---
title: Vision & Image Paste
description: Paste screenshots and images into the CLI for forecast-source inspection.
sidebar_label: Vision & Image Paste
sidebar_position: 7
---

# Vision & Image Paste

Superforecasting Agent supports multimodal vision in the CLI. You can paste screenshots, charts, resolver pages, market screens, reports, or source images and ask a vision-capable model to inspect them.

Vision is source-inspection support, not durable forecast state. A screenshot or image summary does not become evidence, a model run, a resolution, a score, or a calibration lesson until you explicitly record it in the forecast ledger with source metadata and an as-of timestamp.

## How It Works

1. Copy an image to your clipboard.
2. Attach it with `/paste` or a supported paste path.
3. Type your question and submit the message.
4. The image appears as an attachment badge above the input.
5. The image is sent to the model as a vision content block, or summarized by the configured auxiliary vision model for text-only models.

You can attach multiple images before sending. Press `Ctrl+C` to clear all attached images.

New profiles save pasted images under `~/.superforecasting-agent/images/` with timestamped filenames. Migrated profiles may still use `~/.hermes/images/`.

## Forecast Uses

Vision is useful for:

- checking a chart before importing its underlying data
- reading a screenshot of a resolver page or official source
- inspecting a market screen when no structured adapter is available
- summarizing a report image before deciding whether to capture it as evidence
- reviewing dashboard, TUI, or benchmark-output screenshots while developing the fork

Prefer structured source adapters, URLs, and file imports whenever possible. Screenshots are harder to audit and easier to misread than timestamped source snapshots.

## Paste Methods

### `/paste` Command

Use `/paste` when the clipboard contains an image or when the terminal rewrites normal paste keys:

```text
/paste
```

The command checks your clipboard for an image and attaches it.

### Ctrl+V / Cmd+V

Paste handling is layered:

- normal text paste first
- native clipboard or OSC52 text fallback if terminal text paste was incomplete
- image attach when the clipboard or pasted payload resolves to an image or image path

This means macOS screenshot temp paths and `file://...` image URIs can attach immediately instead of landing as raw text.

:::warning
If your clipboard has only an image and no text, most terminals cannot send binary image bytes directly. Use `/paste` as the explicit image-attach fallback.
:::

### `/terminal-setup` for VS Code / Cursor / Windsurf

If you run the TUI inside a local VS Code-family integrated terminal on macOS, `/terminal-setup` can install recommended `workbench.action.terminal.sendSequence` bindings:

```text
/terminal-setup
```

Run it on the local machine only, not inside an SSH session.

## Platform Compatibility

| Environment | `/paste` | Cmd/Ctrl+V | `/terminal-setup` | Notes |
|---|:---:|:---:|:---:|---|
| macOS Terminal / iTerm2 | Yes | Yes | n/a | Native clipboard plus screenshot-path recovery |
| Apple Terminal | Yes | Yes | n/a | If navigation keys are rewritten, use Ctrl+A / Ctrl+E / Ctrl+U |
| Linux X11 desktop | Yes | Yes | n/a | Requires `xclip` |
| Linux Wayland desktop | Yes | Yes | n/a | Requires `wl-paste` |
| WSL2 with Windows Terminal | Yes | Yes | n/a | Uses `powershell.exe` |
| VS Code / Cursor / Windsurf local terminal | Yes | Yes | Yes | Recommended for keybinding parity |
| VS Code / Cursor / Windsurf over SSH | No | No | No | Run `/terminal-setup` locally instead |
| SSH terminal | No | No | n/a | Remote clipboard is not available |

## Platform-Specific Setup

### macOS

No setup is required. The runtime uses `osascript` to read the clipboard. For faster performance, optionally install `pngpaste`:

```bash
brew install pngpaste
```

### Linux X11

Install `xclip`:

```bash
sudo apt install xclip
```

Use the equivalent package-manager command for Fedora, Arch, or another distribution.

### Linux Wayland

Install `wl-clipboard`:

```bash
sudo apt install wl-clipboard
```

Check the active session type with:

```bash
echo $XDG_SESSION_TYPE
```

### WSL2

No extra setup is required. WSL2 uses `powershell.exe` to access the Windows clipboard through .NET. Clipboard image data is transferred as base64-encoded PNG over stdout.

If WSLg is present, the runtime tries PowerShell first, then falls back to `wl-paste`. WSLg clipboard images may arrive as BMP; the runtime converts them to PNG using Pillow or ImageMagick when available.

## SSH & Remote Sessions

Clipboard image paste does not fully work over SSH. Clipboard tools run on the remote host, so they read the remote clipboard rather than your local clipboard.

Workarounds:

- Upload the image file to the remote host and reference it by path.
- Use a URL when the image is publicly accessible.
- Use X11 forwarding with `ssh -X` when you have a local X server.
- Send images through a messaging platform such as Telegram, Discord, Slack, or WhatsApp.

## Why Terminals Cannot Paste Images

Terminals are text-based interfaces. When you press Ctrl+V or Cmd+V, the terminal emulator usually:

1. Reads clipboard text.
2. Wraps it in bracketed-paste escape sequences.
3. Sends that text to the application.

If the clipboard contains only an image, there is no standard binary image payload for the terminal to send. The runtime therefore calls OS-level clipboard tools directly.

## Supported Models

Image paste works with any vision-capable model. The image is sent as a base64-encoded data URL in the OpenAI-style vision content format:

```json
{
  "type": "image_url",
  "image_url": {
    "url": "data:image/png;base64,..."
  }
}
```

Many modern models support this format, including GPT vision models, Claude with vision, Gemini, and open-source multimodal models served through OpenRouter.

## Image Routing

When a user attaches an image from the CLI clipboard, a gateway upload, or another entry point, the runtime checks whether the active model supports vision:

| Model capability | What happens |
|---|---|
| Vision-capable | The image is sent as pixels using the provider's native image format. |
| Text-only | The image is routed through `vision_analyze`; an auxiliary vision model describes it and the text summary is injected into the conversation. |

The auxiliary model is configured under `auxiliary.vision`; see [Auxiliary Models](/user-guide/configuration#auxiliary-models).

### `vision_analyze`

The `vision_analyze` tool follows the same routing. When the active model and provider can carry image content inside tool results, the tool returns the raw image payload to the main model. Otherwise, it asks the configured auxiliary vision model for a plain-text description.

Either path is an inspection aid. Record any forecast-relevant claim separately in the ledger before relying on it for an update, score, resolution, or postmortem.
