# YouTube Audio & Transcript Fetcher

A toolkit for fetching audio and transcripts from YouTube channels. All scripts use CLI arguments — no hardcoding needed.

## Setup

```bash
pip install -r requirements.txt
```

For GPU support (replace `cu121` with your CUDA version):
```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

Requires `ffmpeg` installed on your system for audio conversion.

---

## Scripts

### `transcribe.py` — Unified transcription (recommended)

Fetches transcripts using YouTube's API first, falls back to **faster-whisper + distil-large-v3** for videos without captions. Audio is downloaded as Opus/OGG (64 kbps mono) for the Whisper fallback and deleted after transcription.

> **Note:** `distil-large-v3` is English-only. For non-English channels, override with `--model Systran/faster-whisper-large-v3` (multilingual, slightly slower).

```bash
# Transcribe videos 1–20
python transcribe.py https://www.youtube.com/@channel/videos --start 1 --end 20

# Transcribe all videos
python transcribe.py https://www.youtube.com/@channel/videos

# Upload transcripts to Telegram instead of saving locally
python transcribe.py https://www.youtube.com/@channel/videos --no-save-local --send-telegram

# Save locally AND send to Telegram
python transcribe.py https://www.youtube.com/@channel/videos --send-telegram

# Keep Whisper fallback audio files
python transcribe.py https://www.youtube.com/@channel/videos --keep-audio

# Use the multilingual model
python transcribe.py https://www.youtube.com/@channel/videos --model Systran/faster-whisper-large-v3
```

### `fetcher.py` — Audio-only download

```bash
# Download audio for videos 1–10
python fetcher.py https://www.youtube.com/@channel/videos --start 1 --end 10

# Download all videos
python fetcher.py https://www.youtube.com/@channel/videos
```

### `transcript_fetcher.py` — YouTube captions only (no Whisper)

```bash
# Fetch captions for videos 1–10
python transcript_fetcher.py https://www.youtube.com/@channel/videos --start 1 --end 10

# Fetch all, with language fallback
python transcript_fetcher.py https://www.youtube.com/@channel/videos --languages en es
```

### `transcriber.py` — Whisper-only (for already downloaded audio)

```bash
# Transcribe all audio in a channel folder
python transcriber.py Channel_Name

# Override model/language
python transcriber.py Channel_Name --model Systran/faster-whisper-large-v3 --language en --no-timestamps
```

---

## Output Structure

```
channels/
└── Channel_Name/
    ├── audios/         <- fetcher.py output
    └── transcripts/    <- transcript files (from any script)
```

Transcript files include a source header:
```
# Video Title
# source: youtube-api

[0.0s] Hello and welcome...
[3.5s] Today we're going to...
```

Filenames are indexed and titled: `01_Video_Title.txt`, `02_Another_Video.txt`, etc.

---

## CLI Options

### Common to all scripts

| Flag | Description | Default |
|------|-------------|---------|
| `--start` | First video index (1 = most recent) | `1` |
| `--end` | Last video index (omit for all) | all |
| `--base-dir` | Root output directory | `./channels` |
| `--languages` | Preferred transcript languages | `en` |

### `transcribe.py` only

| Flag | Description | Default |
|------|-------------|---------|
| `--model` | HuggingFace model name (CTranslate2 format) | `Systran/faster-distil-whisper-large-v3` |
| `--device` | `cuda` or `cpu` | auto-detect |
| `--compute-type` | `float16` / `int8_float16` / `int8` | `float16` |
| `--timestamps` / `--no-timestamps` | Include timestamps in output | `true` |
| `--keep-audio` / `--no-keep-audio` | Keep Whisper fallback audio | `false` |
| `--save-local` / `--no-save-local` | Save transcripts to disk | `true` |
| `--send-telegram` / `--no-send-telegram` | Upload transcripts to Telegram | `false` |

---

## config.yaml

Whisper and storage defaults — avoids passing flags every time. All values can be overridden via CLI.

```yaml
model: "Systran/faster-distil-whisper-large-v3"   # HF model name (CTranslate2 format)
device: "cuda"              # cuda | cpu
compute_type: "float16"     # float16 | int8_float16 | int8
language: "en"              # distil-large-v3 is English-only
return_timestamps: true     # timestamped segments vs plain text
keep_audio: false           # keep Whisper fallback audio files

# transcript storage — at least one must be true
save_local: true            # save .txt files locally
send_telegram: false        # upload transcripts to Telegram channel
```

---

## Telegram Setup

To enable Telegram transcript uploads, create a `.env` file in the project root:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHANNEL_ID=@yourchannel_or_-100xxxxxxxxx
```

1. Create a bot via [@BotFather](https://t.me/BotFather) to get a token
2. Add the bot as an admin to your channel
3. Use `@channelname` or the numeric chat ID (e.g. `-1001234567890`) as `TELEGRAM_CHANNEL_ID`
