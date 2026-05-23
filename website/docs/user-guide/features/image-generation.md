---
title: Image Generation
description: Generate auxiliary forecast visuals through FAL.ai or the managed Tool Gateway.
sidebar_label: Image Generation
sidebar_position: 6
---

# Image Generation

Superforecasting Agent can generate images from text prompts through FAL.ai or the managed Tool Gateway. In a forecast desk, this is an auxiliary communication feature: use it for scenario illustrations, briefing visuals, title images, and stakeholder-facing summaries.

Generated images are not evidence, model output, or probability estimates. For charts, calibration plots, and benchmark graphics, prefer code-generated figures backed by ledger data. If an image is sent to a messaging platform, it is delivered as a visual artifact; it does not modify forecast state.

## Supported Models

The built-in FAL picker includes models such as:

| Model | Typical use |
|---|---|
| `fal-ai/flux-2/klein/9b` | Fast general-purpose images |
| `fal-ai/flux-2-pro` | Higher-fidelity photorealistic scenes |
| `fal-ai/z-image/turbo` | Fast multilingual prompt support |
| `fal-ai/nano-banana-pro` | Text-heavy or reasoning-heavy prompts |
| `fal-ai/gpt-image-1.5` | Strong prompt adherence |
| `fal-ai/gpt-image-2` | Text rendering and photorealistic scenes |
| `fal-ai/ideogram/v3` | Typography-focused images |
| `fal-ai/recraft/v4/pro/text-to-image` | Design and brand-style assets |
| `fal-ai/qwen-image` | Complex text and multilingual prompts |

Provider availability, latency, and pricing can change. Check [fal.ai](https://fal.ai/) or your managed Tool Gateway account for current details.

## Setup

:::tip Managed Tool Gateway
Paid Nous Portal users can route image generation through the [Tool Gateway](tool-gateway.md) without a direct FAL API key. If a specific model is not proxied by the managed gateway, choose a different model or configure direct FAL access.
:::

### Direct FAL Access

1. Sign up at [fal.ai](https://fal.ai/).
2. Generate an API key from the FAL dashboard.
3. Store it as `FAL_KEY` in the configured environment file.

### Configure the Backend and Model

Run:

```bash
superforecasting-agent tools
```

Open the Image Generation section, choose either managed gateway or direct FAL access, then select a model. The selection is stored in `~/.superforecasting-agent/config.yaml`:

```yaml
image_gen:
  model: fal-ai/flux-2/klein/9b
  use_gateway: false
```

Migrated profiles may still read the same settings from `~/.hermes/config.yaml`.

## Usage

The agent-facing schema is intentionally small. Ask for the visual, orientation, and any constraints:

```text
Generate a square image for a forecast review packet about semiconductor export controls.
```

```text
Create a landscape scenario illustration for a climate-risk briefing. Do not include numbers or source claims.
```

```text
Make a neutral title image for the monthly calibration review.
```

Use code or charting tools instead when the output should represent actual probabilities, scores, evidence counts, model results, or historical data.

## Aspect Ratios

Every model accepts the same three aspect ratios from the agent's perspective. The runtime translates them into each provider's native schema:

| Agent input | Output shape |
|---|---|
| `landscape` | Wide briefing image |
| `square` | Social or report thumbnail |
| `portrait` | Vertical post or mobile image |

Per-model payload details are handled internally by `_build_fal_payload()`.

## GPT-Image Quality

For GPT-image models, request quality is pinned to a predictable middle tier. The UI does not expose low and high tiers because cost can vary substantially by tier. Select a different model when speed, cost, typography, or photorealism matters more than the default.

## Automatic Upscaling

Upscaling is enabled only for models where the runtime metadata marks it as useful. If upscaling fails because of rate limits, provider errors, or network issues, the original generated image is returned.

## Internal Flow

1. `_resolve_fal_model()` reads `image_gen.model`, falls back to `FAL_IMAGE_MODEL`, then to the default model.
2. `_build_fal_payload()` maps the requested aspect ratio to the selected model's native format and drops unsupported parameters.
3. `_submit_fal_request()` routes through direct FAL credentials or the managed gateway.
4. Optional upscaling runs only for models that enable it.
5. The final image URL is returned to the agent, which can emit it as media for CLI or messaging delivery.

## Debugging

Enable debug logging:

```bash
export IMAGE_TOOLS_DEBUG=true
```

Debug records are written under the local logs directory with per-call model, parameter, timing, and error details. Do not treat debug logs as durable forecast evidence unless they are explicitly captured into the ledger with source metadata.

## Platform Delivery

| Platform | Delivery |
|---|---|
| CLI | Image URL printed as markdown |
| Telegram | Photo message with the prompt as caption |
| Discord | Embedded message |
| Slack | URL unfurled by Slack |
| WhatsApp | Media message |
| Others | URL in plain text |

## Limitations

- Requires direct `FAL_KEY` credentials or managed Tool Gateway access.
- Text-to-image only; inpainting, image editing, and image-to-image workflows are not part of this tool.
- Provider URLs may expire after hours or days.
- Unsupported per-model parameters are filtered before submission.
- Generated visuals are illustrative unless backed by separate ledgered data.
