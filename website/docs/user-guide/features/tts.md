---
sidebar_position: 9
title: "Voice & TTS"
description: "Use speech output and voice transcription for forecast-desk messaging workflows."
---

# Voice & TTS

Superforecasting Agent supports text-to-speech output and voice-message transcription across messaging surfaces. Voice is a supporting channel for forecast review, alerts, approvals, and dictated notes. It is not a forecast lifecycle primitive.

Use voice when it helps operators consume or submit forecast-desk information:

- read a stale-forecast alert aloud
- deliver a review digest in a messaging channel
- transcribe a spoken source note or analyst instruction
- turn a forecast summary into an audio attachment

The forecast ledger still owns probabilities, evidence, assumptions, model runs, resolutions, scores, postmortems, calibration lessons, and domain error profiles. A transcript or generated audio file only affects a forecast after it is explicitly added through the forecast workflow.

:::tip Nous Subscribers
If you have a paid [Nous Portal](https://portal.nousresearch.com) subscription, OpenAI TTS can be available through the [Tool Gateway](./tool-gateway) without a separate OpenAI API key. Run `superforecasting-agent model` or `superforecasting-agent tools` to enable it.
:::

## Text-to-Speech

Text-to-speech converts forecast-desk text into audio for CLI output, messaging delivery, or operator review.

Supported provider families include:

| Provider | Typical use | API key |
|----------|-------------|---------|
| Edge TTS | Free default voice output | None |
| ElevenLabs | High-quality paid voices | `ELEVENLABS_API_KEY` |
| OpenAI TTS | General hosted TTS | `VOICE_TOOLS_OPENAI_KEY` |
| MiniMax TTS | High-quality hosted voices | `MINIMAX_API_KEY` |
| Mistral Voxtral TTS | Hosted voice output | `MISTRAL_API_KEY` |
| Google Gemini TTS | Gemini voice output | `GEMINI_API_KEY` |
| xAI TTS | xAI-hosted voice output | `XAI_API_KEY` |
| NeuTTS | Local TTS | None |
| KittenTTS | Local TTS | None |
| Piper | Local TTS | None |
| Command provider | Any local CLI you configure | Depends on command |

### Platform Delivery

| Platform | Delivery | Format |
|----------|----------|--------|
| Telegram | Voice bubble when Opus/OGG is available | Opus `.ogg` |
| Discord | Voice bubble or audio attachment | Opus/MP3 |
| WhatsApp | Audio attachment | MP3 |
| CLI | Local audio cache | MP3 |

New forecast profiles use `~/.superforecasting-agent/audio_cache/`. Legacy `~/.hermes/audio_cache/` remains readable during migration.

### Configuration

```yaml
# ~/.superforecasting-agent/config.yaml
tts:
  provider: edge
  speed: 1.0
  edge:
    voice: en-US-AriaNeural
  openai:
    model: gpt-4o-mini-tts
    voice: alloy
    speed: 1.0
  minimax:
    model: speech-2.8-hd
    voice_id: English_Graceful_Lady
  mistral:
    model: voxtral-mini-tts-2603
  gemini:
    model: gemini-2.5-flash-preview-tts
    voice: Kore
  xai:
    voice_id: eve
  piper:
    voice: en_US-lessac-medium
```

Legacy `~/.hermes/config.yaml` remains readable during migration.

### Input Length Limits

Each provider has a per-request input-character cap. The runtime truncates text before calling the provider so a long forecast digest does not fail at the provider boundary.

| Provider | Default cap |
|----------|------------:|
| Edge TTS | 5000 |
| OpenAI | 4096 |
| xAI | 15000 |
| MiniMax | 10000 |
| Mistral | 4000 |
| Google Gemini | 5000 |
| ElevenLabs | Model-aware |
| NeuTTS | 2000 |
| KittenTTS | 2000 |

Override per provider:

```yaml
tts:
  openai:
    max_text_length: 8192
```

### Telegram Voice Bubbles And ffmpeg

Telegram voice bubbles require Opus/OGG audio. Providers that emit MP3 or WAV need `ffmpeg` for conversion.

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Fedora
sudo dnf install ffmpeg
```

Without `ffmpeg`, audio is delivered as a regular file attachment.

### xAI Custom Voices

xAI supports custom voice IDs created in the [xAI Console](https://console.x.ai/team/default/voice/voice-library).

```yaml
tts:
  provider: xai
  xai:
    voice_id: "your-custom-voice-id"
```

Use `superforecasting-agent auth add xai-oauth` or set `XAI_API_KEY` according to the provider setup you use elsewhere.

### Piper Local TTS

Piper is a local neural TTS engine. Install through the tools setup flow:

```bash
superforecasting-agent tools
```

Or install manually:

```bash
pip install piper-tts
```

Piper voices are cached under `~/.superforecasting-agent/cache/piper-voices/` in new profiles. Legacy `~/.hermes/cache/piper-voices/` remains migration-compatible.

### Custom command providers

Custom command providers let you use any local TTS engine that exposes a CLI. This is useful for local models, voice-cloning scripts, domain-specific voices, or internal speech systems.

Declare providers under `tts.providers.<name>`:

```yaml
tts:
  provider: voxcpm
  providers:
    voxcpm:
      type: command
      command: "voxcpm --ref ~/voice.wav --text-file {input_path} --out {output_path}"
      output_format: mp3
      timeout: 180
      voice_compatible: true

    piper-custom:
      type: command
      command: "piper -m /path/to/custom.onnx -f {output_path} < {input_path}"
      output_format: wav
```

The runtime writes input text to a temporary UTF-8 file, runs the configured command, then reads the produced audio file.

Placeholders:

| Placeholder | Meaning |
|-------------|---------|
| `{input_path}` | Path to the temp UTF-8 text file |
| `{text_path}` | Alias for `{input_path}` |
| `{output_path}` | Path the command must write audio to |
| `{format}` | `mp3`, `wav`, `ogg`, or `flac` |
| `{voice}` | Configured voice value |
| `{model}` | Configured model value |
| `{speed}` | Resolved speed multiplier |

Optional keys:

| Key | Default | Meaning |
|-----|---------|---------|
| `timeout` | `120` | Seconds before the process tree is killed |
| `output_format` | `mp3` | Audio format to expect |
| `voice_compatible` | `false` | Convert to Opus/OGG for voice-bubble delivery when possible |
| `max_text_length` | `5000` | Truncate input before the command |
| `voice` / `model` | empty | Placeholder values only |

Command providers run with your user's permissions. The runtime quotes placeholder values and enforces the timeout, but the command template itself is trusted local input.

## Voice Message Transcription (STT)

Voice messages sent on Telegram, Discord, WhatsApp, Slack, Signal, and similar messaging surfaces can be transcribed and injected as text. The forecast desk sees the transcript as operator input.

Transcripts are not evidence by default. If a voice note contains a source claim, analyst observation, or probability rationale, add it to the relevant forecast explicitly:

```bash
forecast evidence add <id> --source "voice-note" --summary "..."
forecast update <id>
```

### Configuration

```yaml
# ~/.superforecasting-agent/config.yaml
stt:
  provider: local
  local:
    model: base
  openai:
    model: whisper-1
  mistral:
    model: voxtral-mini-latest
  xai:
    model: grok-stt
```

### Provider Details

| Provider | Notes | API key |
|----------|-------|---------|
| Local Whisper | Uses local `faster-whisper` when installed | None |
| Groq Whisper API | Hosted fallback | `GROQ_API_KEY` |
| OpenAI API | Whisper and newer transcription models | `VOICE_TOOLS_OPENAI_KEY` or `OPENAI_API_KEY` |
| Mistral Voxtral | Transcription with language and timestamp support | `MISTRAL_API_KEY` |
| xAI Grok STT | xAI-hosted transcription | `XAI_API_KEY` |
| Local command | Any configured ASR command | Depends on command |

Local Whisper model sizes:

| Model | Size | Speed | Quality |
|-------|------|-------|---------|
| `tiny` | about 75 MB | Fastest | Basic |
| `base` | about 150 MB | Fast | Good |
| `small` | about 500 MB | Medium | Better |
| `medium` | about 1.5 GB | Slower | Great |
| `large-v3` | about 3 GB | Slowest | Best |

Custom local command transcription uses a forecast-native environment variable, with inherited Hermes names accepted for migrated installs:

```bash
export SUPERFORECASTING_AGENT_LOCAL_STT_COMMAND='whisper-cli {input_path} --output-dir {output_dir}'
```

Your command can use `{input_path}`, `{output_dir}`, `{language}`, and `{model}`. It must write a `.txt` transcript somewhere under `{output_dir}`. `FORECAST_LOCAL_STT_COMMAND` and legacy `HERMES_LOCAL_STT_COMMAND` are compatibility aliases.

### Example: Doubao / Volcengine ASR

```bash
pip install doubao-speech
export VOLCENGINE_APP_ID="your-app-id"
export VOLCENGINE_ACCESS_TOKEN="your-access-token"
export SUPERFORECASTING_AGENT_LOCAL_STT_COMMAND='doubao-speech transcribe {input_path} --out {output_dir}/transcript.txt'
```

```yaml
stt:
  provider: local_command
```

### Fallback Behavior

If the configured provider is unavailable, the runtime falls back where possible:

- local `faster-whisper` unavailable: try local `whisper` CLI or `SUPERFORECASTING_AGENT_LOCAL_STT_COMMAND`
- Groq key missing: fall back to local transcription, then OpenAI if configured
- OpenAI key missing: fall back to local transcription, then Groq if configured
- Mistral key or SDK missing: skip in auto-detect
- no provider available: pass the voice message through with a note

## Forecasting Guidance

- Use TTS for alerts, digests, review queues, and accessible summaries.
- Use STT for operator notes, approvals, and dictated source observations.
- Do not let voice transcripts mutate probabilities automatically.
- Add any forecast-relevant transcript to the ledger with source, timestamp, and reviewer context.
- For backtests or benchmark comparisons, record whether voice/STT material was part of the research input.
