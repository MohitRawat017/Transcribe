# YouTube to Blog Pipeline

Fetch YouTube transcripts, fall back to yt-dlp plus Whisper when captions are not
available, turn transcripts into Markdown blog posts, and publish Blogger drafts.
The pipeline can run from the CLI or through the local web app.

Run every script from the repo root. Scripts resolve `config.yaml`, `.env`,
`client_secret.json`, and `token.json` relative to the root.

## Structure

```text
backend/              FastAPI app, job store, orchestration
frontend/             React/Vite control room UI
transcription/        transcript API plus yt-dlp/Whisper fallback
blog/                 blog generation and Blogger publishing
tests/                unit tests for backend, blog, publish, yt-dlp helpers
config.yaml           Whisper and LLM defaults
requirements.txt      transcription/blog dependencies
requirements-web.txt  FastAPI web dependencies
workspaces/           resumable channel outputs, ignored by git
data/                 SQLite job database, ignored by git
cookies/              optional YouTube cookies, ignored by git
```

## Local Web App

```bash
pip install -r requirements-web.txt
cd frontend
npm install
npm run build
cd ..
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, connect Blogger locally if needed, paste a channel
URL, and choose a required start/end range. Repeated channel runs resume from the
same workspace and skip already-published Blogger drafts through `published.json`.

## CheapCUDA GPU Deployment

The production Docker path runs the full web app plus Whisper fallback in one GPU
container. It installs `ffmpeg`, Deno, and `yt-dlp[default]` for current YouTube
EJS challenge support. The compose file binds to localhost only; reach it with an
SSH tunnel instead of exposing the app publicly.

```bash
docker compose build
docker compose up -d
ssh -L 8000:127.0.0.1:8000 user@server
```

Prepare these files/directories on the server before `docker compose up`:

```text
.env                  LLM/Blogger config; use .env.example as the template
token.json            Blogger OAuth token generated locally, writable for refresh
client_secret.json    Blogger OAuth client secret
workspaces/           persistent channel outputs
data/                 persistent FastAPI job database
cookies/              optional cookies/cookies.txt for yt-dlp retry only
```

In production, keep `DISABLE_BROWSER_OAUTH=1`. Generate or reconnect Blogger
OAuth locally, upload `token.json`, then use Check token in the UI.

## CLI Pipeline

```bash
# API captions first, Whisper fallback for videos without captions
python transcription/transcribe.py https://www.youtube.com/@channel/videos --start 1 --end 20

# Generate Markdown posts from transcripts
python blog/blogify.py Channel_Name

# Publish Blogger drafts
python blog/publish.py Channel_Name --draft
```

## Configuration

```yaml
model: "Systran/faster-distil-whisper-large-v3"
device: "cuda"
compute_type: "float16"
return_timestamps: true
keep_audio: false
save_local: true
send_telegram: false

llm:
  base_url: "https://api.groq.com/openai/v1"
  api_key_env: "GROQ_API_KEY"
  model: "llama-3.3-70b-versatile"
  temperature: 0.7
```

Useful deployment env vars:

```text
GROQ_API_KEY=
LLM_API_KEY=
BLOGGER_BLOG_ID=
DISABLE_BROWSER_OAUTH=1
YTDLP_USE_COOKIES=auto
YTDLP_COOKIE_PATH=/app/cookies/cookies.txt
YTDLP_USER_AGENT=Mozilla/5.0 ...
YTDLP_SLEEP_MIN=3
YTDLP_SLEEP_MAX=6
```

## Verification

```bash
python -m unittest discover -s tests
cd frontend && npm run build
python transcription/transcribe.py --help
```

First CheapCUDA smoke test:

1. Run a range `1-1` where YouTube transcript API succeeds; expect `youtube-api`.
2. Run a range `1-1` that requires audio fallback; expect `yt-dlp:no-cookies` or
   `yt-dlp:cookies`.
3. Rerun the same range; expect workspace resume and Blogger ledger skip.
