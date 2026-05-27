import argparse
import os
import re
import sys
import time
import yaml
import torch
import whisper
import yt_dlp
from pathlib import Path
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled


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
    """e.g. 01_My_Video_Title.txt"""
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
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(audio_dir, "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }],
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={vid_id}"])
        return os.path.join(audio_dir, f"{vid_id}.mp3")
    except yt_dlp.utils.DownloadError as e:
        print(f"    ❌ Audio download failed: {e}")
        return None


def transcribe_audio(audio_path: str, model: whisper.Whisper, language: str, device: str) -> list[dict] | None:
    try:
        result = model.transcribe(
            audio_path,
            language=language,
            fp16=(device == "cuda"),
            verbose=False,
        )
        return result["segments"]
    except Exception as e:
        print(f"    ❌ Whisper failed: {e}")
        return None


def write_transcript(out_path: Path, title: str, segments, source: str, timestamps: bool) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n# source: {source}\n\n")
        if timestamps:
            for s in segments:
                start = s.start if hasattr(s, "start") else s["start"]
                text  = s.text.strip() if hasattr(s, "text") else s["text"].strip()
                f.write(f"[{start:.1f}s] {text}\n")
        else:
            for s in segments:
                text = s.text.strip() if hasattr(s, "text") else s["text"].strip()
                f.write(f"{text}\n")


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
    parser.add_argument("--model", default=cfg.get("model_size", "medium"))
    parser.add_argument("--device", default=cfg.get("device", "cuda" if torch.cuda.is_available() else "cpu"))
    parser.add_argument("--timestamps", action=argparse.BooleanOptionalAction, default=cfg.get("return_timestamps", True))
    parser.add_argument("--keep-audio", action=argparse.BooleanOptionalAction, default=cfg.get("keep_audio", False))
    args = parser.parse_args()

    channel_name = slugify(get_channel_name(args.channel_url))
    transcript_dir = Path(args.base_dir) / channel_name / "transcripts"
    audio_dir      = Path(args.base_dir) / channel_name / "_temp_audio"
    transcript_dir.mkdir(parents=True, exist_ok=True)

    videos = fetch_video_ids(args.channel_url, args.start, args.end)
    total  = len(videos)

    whisper_model = None
    stats = {"api": 0, "whisper": 0, "failed": 0}

    print(f"📝 Saving transcripts to '{transcript_dir}/'...\n" + "─" * 50)
    run_start = time.perf_counter()

    for i, video in enumerate(videos, 1):
        vid_id   = video["id"]
        filename = make_filename(i, total, video["title"])
        out_path = transcript_dir / filename

        t0 = time.perf_counter()
        print(f"[{i}/{total}] {video['title']}")

        if out_path.exists():
            print(f"  ⏭️  Already exists, skipping.\n")
            continue

        # ── Step 1: YouTube Transcript API ──
        snippets = try_api_transcript(vid_id, args.languages)
        if snippets:
            write_transcript(out_path, video["title"], snippets, "youtube-api", args.timestamps)
            print(f"  ✅ API transcript saved. ({fmt_duration(time.perf_counter() - t0)})\n")
            stats["api"] += 1
            continue

        # ── Step 2: Whisper fallback ──
        print(f"  ⚠️  API failed — falling back to Whisper...")

        if whisper_model is None:
            print(f"  🔊 Loading whisper-{args.model} on {args.device}...")
            whisper_model = whisper.load_model(args.model, device=args.device)

        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = download_audio(vid_id, str(audio_dir))

        if audio_path is None:
            print(f"  ❌ Skipping — could not download audio.\n")
            stats["failed"] += 1
            continue

        segments = transcribe_audio(audio_path, whisper_model, args.languages[0], args.device)

        if not args.keep_audio and os.path.exists(audio_path):
            os.remove(audio_path)

        if segments is None:
            print(f"  ❌ Skipping — Whisper transcription failed.\n")
            stats["failed"] += 1
            continue

        write_transcript(out_path, video["title"], segments, "whisper", args.timestamps)
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
