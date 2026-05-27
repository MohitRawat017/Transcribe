# YouTube Audio & Transcript Fetcher

A toolkit for fetching audio and transcripts from YouTube channels. All scripts use CLI arguments — no hardcoding needed.

## Setup

```bash
pip install yt-dlp youtube-transcript-api openai-whisper torch pyyaml
```

Requires `ffmpeg` installed on your system for audio conversion.

## Scripts

### `transcribe.py` — Unified transcription (recommended)

Fetches transcripts using YouTube's API first, falls back to Whisper for videos without captions.

```bash
# Transcribe videos 1–20
python transcribe.py https://www.youtube.com/@channel/videos --start 1 --end 20

# Transcribe all videos
python transcribe.py https://www.youtube.com/@channel/videos

# Keep fallback audio files
python transcribe.py https://www.youtube.com/@channel/videos --keep-audio

# Use a different Whisper model
python transcribe.py https://www.youtube.com/@channel/videos --model large --device cuda
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
python transcriber.py Channel_Name --model large --language en --no-timestamps
```

## Output Structure

```
channels/
└── Channel_Name/
    ├── audios/         ← fetcher.py output
    └── transcripts/    ← transcript files (from any script)
```

Transcript files include a source header:
```
# Video Title
# source: youtube-api

[0.0s] Hello and welcome...
[3.5s] Today we're going to...
```

## CLI Options (common to all scripts)

| Flag | Description | Default |
|------|-------------|---------|
| `--start` | First video index (1 = most recent) | `1` |
| `--end` | Last video index (omit for all) | all |
| `--base-dir` | Root output directory | `./channels` |
| `--languages` | Preferred transcript languages | `en` |

## config.yaml

Whisper defaults — avoids passing flags every time:

```yaml
model_size: "medium"        # tiny | base | small | medium | large
device: "cuda"              # cuda | cpu
language: null              # "en" to skip auto-detect, null = auto
return_timestamps: true     # timestamped segments vs plain text
keep_audio: false           # keep Whisper fallback audio files
```

All config values can be overridden via CLI args.
