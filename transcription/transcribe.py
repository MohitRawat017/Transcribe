import argparse
import gc
import io
import os
import sys
import time
import yaml
import torch
import requests
from pathlib import Path
from dotenv import load_dotenv
from faster_whisper import WhisperModel
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
try:
    from transcription.youtube_access import (
        YoutubeAccessError,
        deno_available,
        download_with_cookie_retry,
        extract_info_with_cookie_retry,
        normalize_channel_url,
        slugify,
    )
except ModuleNotFoundError:
    from youtube_access import (
        YoutubeAccessError,
        deno_available,
        download_with_cookie_retry,
        extract_info_with_cookie_retry,
        normalize_channel_url,
        slugify,
    )

load_dotenv()

TELEGRAM_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")


def load_config(path: str = "config.yaml") -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return yaml.safe_load(f)
    return {}


def get_channel_name(channel_url: str) -> str:
    info, mode = extract_info_with_cookie_retry(
        normalize_channel_url(channel_url),
        {"extract_flat": "in_playlist", "yes_playlist": True, "playlistend": 1},
        "channel metadata",
    )
    print(f"Channel metadata resolved via {mode}.")
    return info.get("channel") or info.get("uploader") or "unknown_channel"


def fetch_video_ids(channel_url: str, start: int, end: int | None) -> list[dict]:
    ydl_opts = {
        "extract_flat": "in_playlist",
        "yes_playlist": True,
        "playliststart": start,
        "ignoreerrors": True,
    }
    if end is not None:
        ydl_opts["playlistend"] = end

    print(f"Scanning channel (videos {start}-{'all' if end is None else end})...")
    info, mode = extract_info_with_cookie_retry(normalize_channel_url(channel_url), ydl_opts, "channel listing")

    if not info or "entries" not in info:
        print("Error: could not fetch channel info. Check the URL.")
        sys.exit(1)

    videos = [
        {"id": e["id"], "title": e.get("title", "Unknown")}
        for e in info["entries"]
        if e and e.get("id") and not e["id"].startswith("UC")
    ]
    print(f"Found {len(videos)} videos via {mode}.\n")
    return videos


def make_filename(index: int, max_index: int, title: str) -> str:
    pad = len(str(max_index))
    return f"{str(index).zfill(pad)}_{slugify(title)}.txt"


def try_api_transcript(vid_id: str, languages: list[str]) -> list | None:
    try:
        ytt = YouTubeTranscriptApi()
        return list(ytt.fetch(vid_id, languages=languages))
    except (TranscriptsDisabled, NoTranscriptFound):
        return None
    except Exception:
        return None


def download_audio(vid_id: str, audio_dir: str) -> tuple[str, str] | None:
    if not deno_available():
        print("  Deno is not available on PATH. Install Deno so yt-dlp can run YouTube EJS challenges.")
        return None

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(audio_dir, "%(id)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "opus",
            "preferredquality": "64",
        }],
        "postprocessor_args": ["-ac", "1"],
    }
    try:
        mode = download_with_cookie_retry([f"https://www.youtube.com/watch?v={vid_id}"], ydl_opts, "audio download")
    except YoutubeAccessError as e:
        print(f"  Audio download failed: {e}")
        return None

    for ext in ("opus", "ogg", "webm", "m4a", "mp3"):
        candidate = os.path.join(audio_dir, f"{vid_id}.{ext}")
        if os.path.exists(candidate):
            print(f"  Audio download succeeded via {mode}.")
            return candidate, mode

    print(f"  Audio file not found after download for {vid_id}")
    return None


def transcribe_audio(audio_path: str, model: WhisperModel, language: str) -> list | None:
    try:
        segments, info = model.transcribe(
            audio_path,
            language=language,
            beam_size=5,
            vad_filter=True,
        )
        duration = info.duration
        result = []
        for seg in segments:
            result.append(seg)
            pct = int(seg.end / duration * 30) if duration else 0
            bar = "#" * pct + "-" * (30 - pct)
            print(f"\r  [{bar}] {seg.end / duration * 100:5.1f}%", end="", flush=True)
        print()
        return result
    except Exception as e:
        print(f"\n  Whisper failed: {e}")
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
    if not TELEGRAM_TOKEN or not TELEGRAM_CHANNEL_ID:
        print("  Warning: Telegram env vars not set, skipping upload.")
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
            print(f"  Telegram upload failed ({resp.status_code}): {err}")
            return False
        return True
    except Exception as e:
        print(f"  Telegram upload failed: {e}")
        return False


def fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m else f"{s}s"


def main():
    cfg = load_config()

    parser = argparse.ArgumentParser(description="Transcribe a YouTube channel (API -> Whisper fallback).")
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
    parser.add_argument("--save-local", action=argparse.BooleanOptionalAction, default=cfg.get("save_local", True))
    parser.add_argument("--send-telegram", action=argparse.BooleanOptionalAction, default=cfg.get("send_telegram", False))
    args = parser.parse_args()

    if not args.save_local and not args.send_telegram:
        print("Error: at least one of --save-local or --send-telegram must be enabled.")
        sys.exit(1)

    channel_name   = slugify(get_channel_name(args.channel_url))
    transcript_dir = Path(args.base_dir) / channel_name / "transcripts"
    audio_dir      = Path(args.base_dir) / channel_name / "temp_audio"

    if args.save_local:
        transcript_dir.mkdir(parents=True, exist_ok=True)

    videos = fetch_video_ids(args.channel_url, args.start, args.end)
    total  = len(videos)

    whisper_model = None
    stats = {"api": 0, "whisper": 0, "failed": 0}

    dest = []
    if args.save_local:    dest.append(f"'{transcript_dir}/'")
    if args.send_telegram: dest.append("Telegram")
    print(f"Saving transcripts to {' + '.join(dest)}...")
    print("-" * 60)

    run_start = time.perf_counter()

    max_index = args.end if args.end is not None else args.start + total - 1

    for i, video in enumerate(videos, 1):
        vid_id   = video["id"]
        channel_index = args.start + i - 1
        filename = make_filename(channel_index, max_index, video["title"])
        out_path = transcript_dir / filename

        t0 = time.perf_counter()
        print(f"[{i}/{total}] {video['title']}")

        if args.save_local and out_path.exists():
            print("  Already exists, skipping.\n")
            continue

        snippets = try_api_transcript(vid_id, args.languages)
        if snippets:
            content = build_transcript_text(video["title"], snippets, "youtube-api", args.timestamps)
            if args.save_local:
                save_transcript_locally(out_path, content)
            if args.send_telegram:
                send_transcript_to_telegram(filename, content)
            print(f"  API transcript saved. ({fmt_duration(time.perf_counter() - t0)})\n")
            stats["api"] += 1
            continue

        print("  API failed, falling back to Whisper...")

        if whisper_model is None:
            print(f"  Loading {args.model} on {args.device} ({args.compute_type})...")
            whisper_model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)

        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_result = download_audio(vid_id, str(audio_dir))

        if audio_result is None:
            print("  Skipping: could not download audio.\n")
            stats["failed"] += 1
            continue

        audio_path, audio_source = audio_result
        segments = transcribe_audio(audio_path, whisper_model, args.languages[0])

        if not args.keep_audio and os.path.exists(audio_path):
            os.remove(audio_path)

        if segments is None:
            print("  Skipping: Whisper transcription failed.\n")
            stats["failed"] += 1
            continue

        content = build_transcript_text(video["title"], segments, f"whisper/{audio_source}", args.timestamps)
        if args.save_local:
            save_transcript_locally(out_path, content)
        if args.send_telegram:
            send_transcript_to_telegram(filename, content)
        print(f"  Whisper transcript saved. ({fmt_duration(time.perf_counter() - t0)})\n")
        stats["whisper"] += 1

    if not args.keep_audio and audio_dir.exists() and not any(audio_dir.iterdir()):
        audio_dir.rmdir()

    # release the Whisper model from GPU so it doesn't hold VRAM (e.g. before running Ollama)
    if whisper_model is not None:
        del whisper_model
        gc.collect()
        if args.device == "cuda":
            torch.cuda.empty_cache()

    total_time = fmt_duration(time.perf_counter() - run_start)
    print("-" * 60)
    print(f"API: {stats['api']}  Whisper: {stats['whisper']}  Failed: {stats['failed']}")
    print(f"Total time: {total_time}")


if __name__ == "__main__":
    main()
