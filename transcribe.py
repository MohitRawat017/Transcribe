import argparse
import io
import os
import re
import sys
import time
import yaml
import torch
import yt_dlp
import requests
from pathlib import Path
from dotenv import load_dotenv
from faster_whisper import WhisperModel
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

load_dotenv()

TELEGRAM_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")


def load_config(path: str = "config.yaml") -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return yaml.safe_load(f)
    return {}


def slugify(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name).strip("_")


def get_channel_name(channel_url: str) -> str:
    ydl_opts = {"quiet": True, "extract_flat": True, "playlistend": 1}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
    return info.get("channel") or info.get("uploader") or "unknown_channel"


def fetch_video_ids(channel_url: str, start: int, end: int | None) -> list[dict]:
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "playliststart": start,
        "ignoreerrors": True,
    }
    if end is not None:
        ydl_opts["playlistend"] = end

    print(f"\n🔍 Scanning channel (videos {start}–{'all' if end is None else end})...")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    if not info or "entries" not in info:
        print("❌ Could not fetch channel info. Check the URL.")
        sys.exit(1)

    videos = [
        {"id": e["id"], "title": e.get("title", "Unknown")}
        for e in info["entries"]
        if e and e.get("id") and not e["id"].startswith("UC")
    ]
    print(f"✅ Found {len(videos)} videos.\n")
    return videos


def make_filename(index: int, total: int, title: str) -> str:
    pad = len(str(total))
    return f"{str(index).zfill(pad)}_{slugify(title)}.txt"


def try_api_transcript(vid_id: str, languages: list[str]) -> list | None:
    try:
        ytt = YouTubeTranscriptApi()
        return list(ytt.fetch(vid_id, languages=languages))
    except (TranscriptsDisabled, NoTranscriptFound):
        return None
    except Exception:
        return None


def download_audio(vid_id: str, audio_dir: str) -> str | None:
    """Download audio as Opus at 64kbps mono. Returns path to the produced file."""
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(audio_dir, "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "opus",
            "preferredquality": "64",
        }],
        "postprocessor_args": ["-ac", "1"],  # mono
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={vid_id}"])
    except yt_dlp.utils.DownloadError as e:
        print(f"    ❌ Audio download failed: {e}")
        return None

    # yt-dlp picks the extension based on the codec — usually .opus for opus codec.
    # Glob to find whatever it actually produced.
    for ext in ("opus", "ogg", "webm", "m4a", "mp3"):
        candidate = os.path.join(audio_dir, f"{vid_id}.{ext}")
        if os.path.exists(candidate):
            return candidate

    print(f"    ❌ Audio file not found after download for {vid_id}")
    return None


def transcribe_audio(audio_path: str, model: WhisperModel, language: str) -> list | None:
    """Returns a list of segments (with .start, .end, .text) or None on failure."""
    try:
        segments, _info = model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            vad_filter=True,  # skip silent regions for a small speed-up
        )
        # segments is a generator — materialize it so we can iterate twice if needed
        return list(segments)
    except Exception as e:
        print(f"    ❌ Whisper failed: {e}")
        return None


def build_transcript_text(title: str, segments, source: str, timestamps: bool) -> str:
    lines = [f"# {title}", f"# source: {source}", ""]
    for s in segments:
        text = s.text.strip() if hasattr(s, "text") else s["text"].strip()
        if timestamps:
            start = s.start if hasattr(s, "start") else s["start"]
            lines.append(f"[{start:.1f}s] {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


def save_transcript_locally(out_path: Path, content: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")


def send_transcript_to_telegram(filename: str, content: str) -> bool:
    """Upload transcript text as a .txt document to Telegram channel."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHANNEL_ID:
        print("    ⚠️  Telegram env vars not set — skipping upload.")
        return False
    try:
        url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
        data = {"chat_id": TELEGRAM_CHANNEL_ID, "caption": filename}
        files = {"document": (filename, io.BytesIO(content.encode("utf-8")), "text/plain")}
        resp = requests.post(url, data=data, files=files, timeout=30)
        if not resp.ok:
            try:
                err = resp.json().get("description", resp.text)
            except Exception:
                err = resp.text
            print(f"    ❌ Telegram upload failed ({resp.status_code}): {err}")
            return False
        return True
    except Exception as e:
        print(f"    ❌ Telegram upload failed: {e}")
        return False


def fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m else f"{s}s"


def main():
    cfg = load_config()

    parser = argparse.ArgumentParser(description="Transcribe a YouTube channel (API → Whisper fallback).")
    parser.add_argument("channel_url", help="YouTube channel videos URL")
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=None, help="End index (default: all)")
    parser.add_argument("--base-dir", default="./channels")
    parser.add_argument("--languages", nargs="+", default=["en"])
    parser.add_argument("--model", default=cfg.get("model", "Systran/faster-distil-whisper-large-v3"))
    parser.add_argument("--device", default=cfg.get("device", "cuda" if torch.cuda.is_available() else "cpu"))
    parser.add_argument("--compute-type", default=cfg.get("compute_type", "float16"),
                        help="float16 | int8_float16 | int8 (default: float16)")
    parser.add_argument("--timestamps", action=argparse.BooleanOptionalAction, default=cfg.get("return_timestamps", True))
    parser.add_argument("--keep-audio", action=argparse.BooleanOptionalAction, default=cfg.get("keep_audio", False))
    # Storage flags
    parser.add_argument("--save-local", action=argparse.BooleanOptionalAction, default=cfg.get("save_local", True),
                        help="Save transcripts to local disk (default: true)")
    parser.add_argument("--send-telegram", action=argparse.BooleanOptionalAction, default=cfg.get("send_telegram", False),
                        help="Upload transcripts to Telegram channel (default: false)")
    args = parser.parse_args()

    if not args.save_local and not args.send_telegram:
        print("❌ At least one of --save-local or --send-telegram must be enabled.")
        sys.exit(1)

    channel_name   = slugify(get_channel_name(args.channel_url))
    transcript_dir = Path(args.base_dir) / channel_name / "transcripts"
    audio_dir      = Path(args.base_dir) / channel_name / "_temp_audio"

    if args.save_local:
        transcript_dir.mkdir(parents=True, exist_ok=True)

    videos = fetch_video_ids(args.channel_url, args.start, args.end)
    total  = len(videos)

    whisper_model = None
    stats = {"api": 0, "whisper": 0, "failed": 0}

    dest = []
    if args.save_local:    dest.append(f"'{transcript_dir}/'")
    if args.send_telegram: dest.append("Telegram")
    print(f"📝 Saving transcripts to {' + '.join(dest)}...\n" + "─" * 50)

    run_start = time.perf_counter()

    for i, video in enumerate(videos, 1):
        vid_id   = video["id"]
        filename = make_filename(i, total, video["title"])
        out_path = transcript_dir / filename

        t0 = time.perf_counter()
        print(f"[{i}/{total}] {video['title']}")

        if args.save_local and out_path.exists():
            print(f"  ⏭️  Already exists, skipping.\n")
            continue

        # ── Step 1: YouTube Transcript API ──
        snippets = try_api_transcript(vid_id, args.languages)
        if snippets:
            content = build_transcript_text(video["title"], snippets, "youtube-api", args.timestamps)
            if args.save_local:
                save_transcript_locally(out_path, content)
            if args.send_telegram:
                send_transcript_to_telegram(filename, content)
            print(f"  ✅ API transcript saved. ({fmt_duration(time.perf_counter() - t0)})\n")
            stats["api"] += 1
            continue

        # ── Step 2: Whisper fallback ──
        print(f"  ⚠️  API failed — falling back to Whisper...")

        if whisper_model is None:
            print(f"  🔊 Loading {args.model} on {args.device} ({args.compute_type})...")
            whisper_model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)

        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = download_audio(vid_id, str(audio_dir))

        if audio_path is None:
            print(f"  ❌ Skipping — could not download audio.\n")
            stats["failed"] += 1
            continue

        segments = transcribe_audio(audio_path, whisper_model, args.languages[0])

        if not args.keep_audio and os.path.exists(audio_path):
            os.remove(audio_path)

        if segments is None:
            print(f"  ❌ Skipping — Whisper transcription failed.\n")
            stats["failed"] += 1
            continue

        content = build_transcript_text(video["title"], segments, "whisper", args.timestamps)
        if args.save_local:
            save_transcript_locally(out_path, content)
        if args.send_telegram:
            send_transcript_to_telegram(filename, content)
        print(f"  ✅ Whisper transcript saved. ({fmt_duration(time.perf_counter() - t0)})\n")
        stats["whisper"] += 1

    if not args.keep_audio and audio_dir.exists() and not any(audio_dir.iterdir()):
        audio_dir.rmdir()

    total_time = fmt_duration(time.perf_counter() - run_start)
    print("─" * 50)
    print(f"✅ API: {stats['api']}  |  🎙️ Whisper: {stats['whisper']}  |  ❌ Failed: {stats['failed']}")
    print(f"⏱️  Total time: {total_time}")


if __name__ == "__main__":
    main()
