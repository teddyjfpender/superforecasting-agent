---
sidebar_position: 10
title: "Voice Mode"
description: "Hands-free forecast review and spoken alert delivery."
---

# Voice Mode

Voice mode adds microphone input, speech-to-text, and spoken replies to the
Superforecasting Agent runtime. It is useful for hands-free forecast review,
quick evidence capture, spoken alert delivery, approvals, and Discord voice
channel discussions.

Voice does not replace the forecast ledger. Spoken transcripts and replies are
conversation artifacts until you explicitly create evidence, update a forecast,
resolve a question, score a result, or write a postmortem through the forecast
workflow.

For a practical setup walkthrough, see
[Use Voice Mode with Superforecasting Agent](/guides/use-voice-mode-with-superforecasting-agent).

## Prerequisites

Before enabling voice, make sure:

1. Superforecasting Agent is installed.
2. A model provider is configured with `superforecasting-agent model`.
3. Text mode works in `superforecasting-agent chat` or `superforecasting-agent tui`.
4. The active profile home exists, normally `~/.superforecasting-agent/`.

Legacy `~/.hermes/` homes remain readable during migration, but new forecast
profiles should use the fork-native home.

## Overview

| Feature | Platform | Best for |
| --- | --- | --- |
| Interactive voice | CLI/TUI | Hands-free forecast review and dictated research notes. |
| Spoken replies | Telegram, Discord | Review alerts, source-watch summaries, and approval prompts. |
| Voice channel bot | Discord | Live forecast discussion with text transcript and spoken response. |

Voice mode is a secondary interface. Use it to operate the desk, not as the
source of truth for probabilities, evidence, assumptions, scores, or lessons.

## Install Extras

```bash
# CLI microphone mode and audio playback
pip install "superforecasting-agent[voice]"

# Discord and Telegram messaging
pip install "superforecasting-agent[messaging]"

# Premium ElevenLabs TTS
pip install "superforecasting-agent[tts-premium]"

# Optional local NeuTTS provider
python -m pip install -U neutts[all]

# Everything
pip install "superforecasting-agent[all]"
```

| Extra | Packages | Required for |
| --- | --- | --- |
| `voice` | `sounddevice`, `numpy` | CLI/TUI microphone mode. |
| `messaging` | `discord.py[voice]`, `python-telegram-bot`, `aiohttp` | Discord and Telegram bots. |
| `tts-premium` | `elevenlabs` | ElevenLabs TTS provider. |

`discord.py[voice]` installs the PyNaCl and Opus bindings needed for Discord
voice-channel support.

## System Dependencies

```bash
# macOS
brew install portaudio ffmpeg opus
brew install espeak-ng

# Ubuntu/Debian
sudo apt install portaudio19-dev ffmpeg libopus0
sudo apt install espeak-ng
```

| Dependency | Purpose | Required for |
| --- | --- | --- |
| PortAudio | Microphone input and local playback. | CLI/TUI voice mode. |
| ffmpeg | Audio conversion for messaging and TTS delivery. | All platforms. |
| Opus | Discord voice codec. | Discord voice channels. |
| espeak-ng | NeuTTS phonemizer backend. | Local NeuTTS. |

## API Keys

Add cloud speech keys to `~/.superforecasting-agent/.env` only when needed:

```bash
# Speech-to-text. Local STT needs no key.
GROQ_API_KEY=***
VOICE_TOOLS_OPENAI_KEY=***

# Text-to-speech. Edge TTS and NeuTTS need no key.
ELEVENLABS_API_KEY=***
```

If `faster-whisper` is installed, local speech-to-text can run without cloud
keys. The first local run downloads the selected Whisper model.

## CLI Voice Mode

Voice mode is available in the classic CLI and the TUI:

```bash
superforecasting-agent chat
superforecasting-agent tui
```

Inside the session:

```text
/voice          Toggle voice mode
/voice on       Enable voice mode
/voice off      Disable voice mode
/voice tts      Toggle spoken replies
/voice status   Show current voice state
```

### Recording Flow

1. Press `Ctrl+B`.
2. A start beep plays and recording begins.
3. Speak the forecast question, source note, assumption, or review request.
4. Silence detection stops recording after the configured pause.
5. The audio is transcribed and sent as the next user message.
6. If TTS is enabled, the response is spoken.
7. The loop can restart automatically until you stop it.

The record key is configurable in `~/.superforecasting-agent/config.yaml`:

```yaml
voice:
  record_key: "ctrl+b"
```

### Good CLI Voice Prompts

Use voice for short operational requests:

```text
Review forecast fc_123 for stale evidence and summarize what needs checking.
```

```text
Add this as an evidence candidate for fc_123, but do not update probability until I review it.
```

```text
Read the active macro review queue and flag forecasts whose close date is inside two weeks.
```

For durable updates, review the generated text and then run or confirm the
appropriate `forecast evidence`, `forecast update`, `forecast resolve`,
`forecast score`, or `forecast postmortem` command.

### Silence Detection

The recorder uses a two-stage algorithm:

1. Speech confirmation waits for audio above the RMS threshold.
2. End detection stops after continuous silence.

Defaults:

- `silence_threshold`: `200`
- `silence_duration`: `3.0`
- no-speech timeout: `15` seconds

These values are useful starting points, but noisy rooms may need a higher
threshold or a headset microphone.

### Streaming TTS

When TTS is enabled, replies are spoken sentence by sentence as text is
generated. The runtime:

1. Buffers model deltas into complete sentences.
2. Strips markdown and hidden thinking blocks.
3. Generates and plays audio for each sentence.

For forecast review, prefer concise replies. Long spoken rationales are harder
to audit than text with explicit evidence references.

### Hallucination Filter

Whisper can sometimes produce phantom text from silence or background noise. The
runtime filters common hallucination phrases and repetitive variants before
submitting the transcript.

If phantom transcripts still appear, raise the silence threshold, use local
noise reduction, or switch STT models.

## Gateway Voice Reply

Telegram and Discord can send spoken replies alongside normal text messages.
See the platform setup guides first:

- [Telegram Setup Guide](../messaging/telegram.md)
- [Discord Setup Guide](../messaging/discord.md)

Start the gateway:

```bash
superforecasting-agent gateway
superforecasting-agent gateway setup
```

### Messaging Commands

These commands work in Telegram and Discord text channels or DMs:

```text
/voice          Toggle voice mode
/voice on       Speak only when the inbound message is voice
/voice tts      Speak every reply
/voice off      Disable spoken replies
/voice status   Show current mode
```

### Modes

| Mode | Command | Behavior |
| --- | --- | --- |
| `off` | `/voice off` | Text only. |
| `voice_only` | `/voice on` | Speak replies only after inbound voice messages. |
| `all` | `/voice tts` | Speak every response. |

Voice settings persist across gateway restarts.

### Forecast Desk Usage

Messaging voice is best for:

- spoken review alerts
- source-watch summaries
- quick approvals
- dictated evidence notes
- asking for the next item in a review queue

It should not silently mutate a forecast. Have the agent produce a proposed
ledger action, then confirm the command or update explicitly.

### Platform Delivery

| Platform | Format | Notes |
| --- | --- | --- |
| Telegram | Opus/OGG voice bubble | Plays inline in chat. |
| Discord | Native voice bubble or file fallback | Uses Opus when supported. |

ffmpeg converts audio formats as needed.

## Discord Voice Channels

The Discord voice-channel mode lets the bot join a voice channel, listen to
authorized users, transcribe speech, run a forecast-scoped response, and speak
the reply back in the channel.

Use it for live forecast review meetings. If a spoken point affects a forecast,
capture it as evidence or an assumption with an explicit timestamp before it
changes the probability.

### Bot Permissions

If your Discord bot already works for text, add voice permissions in the Discord
Developer Portal under **Installation** -> **Default Install Settings** ->
**Guild Install**.

| Permission | Purpose | Required |
| --- | --- | --- |
| Connect | Join voice channels. | Yes |
| Speak | Play TTS audio in voice channels. | Yes |
| Use Voice Activity | Detect speakers. | Recommended |

Updated permission integers:

| Level | Integer | Includes |
| --- | --- | --- |
| Text only | `274878286912` | View channels, send messages, read history, embeds, attachments, threads, reactions. |
| Text + voice | `274881432640` | Text permissions plus Connect and Speak. |

Re-invite the bot with:

```text
https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot+applications.commands&permissions=274881432640
```

Replace `YOUR_APP_ID` with the Application ID from the Developer Portal.

### Privileged Gateway Intents

Enable these in the Discord Developer Portal under **Bot** -> **Privileged
Gateway Intents**:

| Intent | Purpose |
| --- | --- |
| Presence Intent | Detect user presence. |
| Server Members Intent | Resolve usernames in `DISCORD_ALLOWED_USERS` when numeric IDs are not used. |
| Message Content Intent | Read text messages in channels. |

Message Content Intent is required. Server Members Intent is optional when
`DISCORD_ALLOWED_USERS` uses numeric Discord user IDs.

### Opus Codec

Install Opus on the gateway host:

```bash
# macOS
brew install opus

# Ubuntu/Debian
sudo apt install libopus0
```

The runtime auto-loads common library names:

- macOS: `/opt/homebrew/lib/libopus.dylib`
- Linux: `libopus.so.0`

### Discord Environment

```bash
# ~/.superforecasting-agent/.env
DISCORD_BOT_TOKEN=***
DISCORD_ALLOWED_USERS=284102345871466496

# Optional cloud speech providers
GROQ_API_KEY=***
VOICE_TOOLS_OPENAI_KEY=***
ELEVENLABS_API_KEY=***
```

Start the gateway:

```bash
superforecasting-agent gateway
```

### Voice Channel Commands

Use these in the Discord text channel where the bot is present:

```text
/voice join      Join your current voice channel
/voice channel   Alias for /voice join
/voice leave     Disconnect from voice channel
/voice status    Show voice mode and connected channel
```

You must be in a voice channel before running `/voice join`.

### Voice Channel Flow

When joined, the bot:

1. Listens to each authorized user's audio stream.
2. Detects speech and silence.
3. Transcribes audio with local, Groq, or OpenAI STT.
4. Runs the forecast-scoped runtime response.
5. Sends the transcript and text reply to the linked text channel.
6. Speaks the reply in the voice channel.

The listener pauses while the bot is speaking so it does not re-process its own
audio.

## Configuration Reference

### config.yaml

```yaml
voice:
  record_key: "ctrl+b"
  max_recording_seconds: 120
  auto_tts: false
  beep_enabled: true
  silence_threshold: 200
  silence_duration: 3.0

stt:
  enabled: true
  provider: "local"
  local:
    model: "base"
  # model: "whisper-1"  # legacy fallback when provider is omitted

tts:
  provider: "edge"
  edge:
    voice: "en-US-AriaNeural"
  elevenlabs:
    voice_id: "pNInz6obpgDQGcFmaJgB"
    model_id: "eleven_multilingual_v2"
  openai:
    model: "gpt-4o-mini-tts"
    voice: "alloy"
    base_url: "https://api.openai.com/v1"
  neutts:
    ref_audio: ''
    ref_text: ''
    model: neuphonic/neutts-air-q4-gguf
    device: cpu
```

Set `stt.enabled: false` if you want the gateway to cache inbound audio and pass
the file path to a custom pipeline without automatic transcription.

### Environment Variables

```bash
# Speech-to-text providers. Local needs no key.
GROQ_API_KEY=***
VOICE_TOOLS_OPENAI_KEY=***

# STT advanced overrides
STT_GROQ_MODEL=whisper-large-v3-turbo
STT_OPENAI_MODEL=whisper-1
GROQ_BASE_URL=https://api.groq.com/openai/v1
STT_OPENAI_BASE_URL=https://api.openai.com/v1

# Text-to-speech providers. Edge TTS and NeuTTS need no key.
ELEVENLABS_API_KEY=***

# Discord voice channel
DISCORD_BOT_TOKEN=***
DISCORD_ALLOWED_USERS=***
DISCORD_REQUIRE_MENTION=true
DISCORD_FREE_RESPONSE_CHANNELS=
```

`VOICE_TOOLS_OPENAI_KEY` enables both OpenAI STT and OpenAI TTS.

### STT Provider Comparison

| Provider | Model | Speed | Quality | Key required |
| --- | --- | --- | --- | --- |
| Local | `base` | Fast on many machines | Good | No |
| Local | `small` | Medium | Better | No |
| Local | `large-v3` | Slow on CPU | Best local model | No |
| Groq | `whisper-large-v3-turbo` | Very fast | Good | Yes |
| Groq | `whisper-large-v3` | Fast | Better | Yes |
| OpenAI | `whisper-1` | Fast | Good | Yes |
| OpenAI | `gpt-4o-transcribe` | Medium | Strong | Yes |

Automatic fallback order is local, then Groq, then OpenAI.

### TTS Provider Comparison

| Provider | Quality | Latency | Key required |
| --- | --- | --- | --- |
| Edge TTS | Good | Low | No |
| NeuTTS | Good | Depends on CPU/GPU | No |
| ElevenLabs | High | Medium | Yes |
| OpenAI TTS | Good | Low-medium | Yes |

See [Text-to-Speech](./tts.md) for provider-specific TTS details.

## Troubleshooting

### No Audio Device Found

PortAudio is usually missing:

```bash
brew install portaudio
sudo apt install portaudio19-dev
```

### Discord Server Channels Do Not Respond

The bot requires a mention by default in server channels.

1. Type `@` and select the bot user, not a role with the same name.
2. Use DMs for no-mention interaction.
3. Set `DISCORD_REQUIRE_MENTION=false` only in channels where broad response is acceptable.

### Bot Joins A Voice Channel But Does Not Hear Me

- Confirm your Discord user ID is in `DISCORD_ALLOWED_USERS`.
- Confirm you are not muted in Discord.
- Speak for a few seconds after the bot joins so the Discord voice websocket can map audio to a user.
- Confirm Opus is installed on the gateway host.

### Bot Hears Me But Does Not Respond

- Verify STT is available with `faster-whisper`, `GROQ_API_KEY`, or `VOICE_TOOLS_OPENAI_KEY`.
- Verify the model provider works in text mode.
- Review gateway logs:

```bash
tail -f ~/.superforecasting-agent/logs/gateway.log
```

Legacy profiles may still write logs under `~/.hermes/logs/`.

### Bot Responds In Text But Not Voice

- Check the selected TTS provider and quota.
- Try the Edge TTS fallback.
- Check logs for TTS conversion errors.
- Confirm `ffmpeg` is installed.

### Whisper Returns Garbage Text

- Use a quieter environment.
- Raise `voice.silence_threshold`.
- Use a headset microphone.
- Try another STT model.

### Forecast State Did Not Change

Voice commands are still forecast-support turns. To modify durable state,
confirm or run the relevant ledger command:

```bash
forecast evidence add <id> --source "<source>" --claim "<claim>"
forecast update <id> --probability 0.62 --rationale "..."
forecast resolve <id> --outcome yes
forecast score <id>
forecast postmortem <id> --summary "..."
```
