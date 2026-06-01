# YouTube → Blog Pipeline

Fetch YouTube transcripts (or transcribe audio with Whisper), turn them into blog posts
with an LLM, and publish to Blogger. All scripts are CLI-driven.

> Run every script **from the repo root** — they resolve `config.yaml` and credential
> files by relative path.

## Structure

```
transcription/        # stage 1: get transcripts
  fetcher.py            audio-only download
  transcript_fetcher.py YouTube captions only
  transcribe.py         API captions + Whisper fallback (recommended)
  transcriber.py        Whisper on already-downloaded audio
blog/                 # stage 2 + 3: generate and publish
  blogify.py            transcript -> blog post (LLM)
  publish.py            blog post -> Blogger
plan/                 # phase1.md (local), phase2.md (docker/deploy)
config.yaml           # whisper + llm + storage defaults
requirements.txt      # transcription deps
requirements-app.txt  # blog deps (used by the Docker image)
channels/             # data: channels/<Channel>/{audios,transcripts,blogs}/
```

## Setup

```bash
pip install -r requirements.txt
```
GPU Whisper (replace `cu121` with your CUDA version):
```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```
Requires `ffmpeg` for audio conversion.

## Local Web App

The web app wraps the CLI pipeline with a local FastAPI backend and React frontend.
Blogger credentials are checked before any transcript work starts.

```bash
pip install -r requirements-web.txt
cd frontend
npm install
npm run build
cd ..
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, connect Blogger if needed, paste a channel URL, and
choose a required start/end range. Each run writes to `runs/<job_id>/` and publishes
drafts only.

## Stage 1 — Transcripts

```bash
# API captions first, Whisper fallback for videos without captions (recommended)
python transcription/transcribe.py https://www.youtube.com/@channel/videos --start 1 --end 20

# captions only (no Whisper)
python transcription/transcript_fetcher.py https://www.youtube.com/@channel/videos

# audio-only download
python transcription/fetcher.py https://www.youtube.com/@channel/videos

# Whisper on already-downloaded audio
python transcription/transcriber.py Channel_Name
```

## Stage 2 — Generate blog posts

```bash
python blog/blogify.py Channel_Name              # transcripts -> blogs/*.md
python blog/blogify.py Channel_Name --overwrite  # regenerate existing
```
Two-pass (outline → write) via an OpenAI-compatible endpoint set in `config.yaml`
(`llm` block). Default is Groq; the API key is read from `.env` as `LLM_API_KEY`.

## Stage 3 — Publish to Blogger

```bash
python blog/publish.py --list-blogs              # find your blog ID
python blog/publish.py Channel_Name --draft      # publish drafts
python blog/publish.py Channel_Name              # publish live
```
Needs Google OAuth: enable Blogger API v3, download `client_secret.json` to the repo
root, set `BLOGGER_BLOG_ID` in `.env`. First run opens a browser and caches `token.json`.

## Docker (blog pipeline)

The image contains the blog stage only (transcription stays on your GPU/Windows machine).

```bash
docker compose build
docker compose run --rm app python blogify.py Channel_Name --overwrite
docker compose run --rm app python publish.py Channel_Name --draft
```
`channels/`, `.env`, `token.json`, and `client_secret.json` are mounted at runtime.
Optional local model on a GPU host: `docker compose --profile gpu up -d vllm`, then set
`llm.base_url` to `http://vllm:8000/v1`.

## config.yaml

```yaml
# Whisper (transcription)
model: "Systran/faster-distil-whisper-large-v3"
device: "cuda"
compute_type: "float16"
language: "en"
return_timestamps: true
keep_audio: false

# transcript storage (at least one true)
save_local: true
send_telegram: false

# blog generation (OpenAI-compatible endpoint)
llm:
  base_url: "https://api.groq.com/openai/v1"
  api_key: "ollama"            # fallback; real key comes from .env LLM_API_KEY
  model: "llama-3.3-70b-versatile"
  temperature: 0.7
```

## .env

```
LLM_API_KEY=your_groq_or_openai_key
BLOGGER_BLOG_ID=1234567890
# optional, for transcribe.py --send-telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHANNEL_ID=@yourchannel
```
