import argparse
import os
import re
import sys
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled


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


def fetch_transcript(video: dict, output_dir: str, languages: list[str]) -> None:
    vid_id = video["id"]
    out_path = os.path.join(output_dir, f"{vid_id}.txt")

    if os.path.exists(out_path):
        print(f"⏭️  Already exists, skipping: {vid_id}\n")
        return

    print(f"📄 Fetching: {video['title']}")
    try:
        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(vid_id, languages=languages)

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(f"# {video['title']}\n\n")
            for s in transcript:
                f.write(f"[{s.start:.1f}s] {s.text.strip()}\n")

        print(f"✅ Saved → {out_path}\n")
    except TranscriptsDisabled:
        print(f"⚠️  Skipped {vid_id} — transcripts disabled.\n")
    except NoTranscriptFound:
        print(f"⚠️  Skipped {vid_id} — no transcript in {languages}.\n")
    except Exception as e:
        print(f"❌  Error for {vid_id}: {e}\n")


def main():
    parser = argparse.ArgumentParser(description="Fetch YouTube transcripts for a channel.")
    parser.add_argument("channel_url", help="YouTube channel videos URL")
    parser.add_argument("--start", type=int, default=1, help="Start index (default: 1)")
    parser.add_argument("--end", type=int, default=None, help="End index (default: all videos)")
    parser.add_argument("--output-dir", default="./channels", help="Base output directory (default: ./channels)")
    parser.add_argument("--languages", nargs="+", default=["en"], help="Preferred transcript languages (default: en)")
    args = parser.parse_args()

    channel_name = slugify(get_channel_name(args.channel_url))
    output_dir = os.path.join(args.output_dir, channel_name, "transcripts")
    os.makedirs(output_dir, exist_ok=True)

    videos = fetch_video_ids(args.channel_url, args.start, args.end)

    print(f"📥 Saving transcripts to '{output_dir}/'...\n" + "─" * 50)
    for i, video in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] ", end="")
        fetch_transcript(video, output_dir, args.languages)

    print("─" * 50)
    print(f"\n🎉 Done! Transcripts in '{output_dir}/'")


if __name__ == "__main__":
    main()
