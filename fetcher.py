import yt_dlp
import os
import sys

# ─────────────────────────────────────────────
#  CONFIG — edit these before running
# ─────────────────────────────────────────────

CHANNEL_URL = "https://www.youtube.com/@zackdfilms/videos"  # URL of the YouTube channel's videos page
START_VIDEO  = 1      # index of first video to fetch (1 = most recent)
END_VIDEO    = 10     # index of last video to fetch
OUTPUT_DIR   = "./audios"

# ─────────────────────────────────────────────


def fetch_video_ids(channel_url: str, start: int, end: int) -> list[dict]:
    """Fetch video IDs and titles from the channel in the given range."""
    print(f"\n🔍 Scanning channel for videos {start}–{end}...")

    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "playliststart": start,
        "playlistend": end,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    if not info or "entries" not in info:
        print("❌ Could not fetch channel info. Check the URL.")
        sys.exit(1)

    videos = [
        {"id": e["id"], "title": e.get("title", "Unknown")}
        for e in info["entries"]
        if e.get("id")
    ]

    print(f"✅ Found {len(videos)} videos in range.\n")
    return videos


def download_audio(video: dict, output_dir: str) -> None:
    """Download audio-only for a single video."""
    video_url = f"https://www.youtube.com/watch?v={video['id']}"

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "quiet": False,
        "no_warnings": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",   # 128kbps is plenty for speech/transcription
        }],
    }

    print(f"⬇️  Downloading: {video['title']}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        print(f"✅ Done: {video['id']}.mp3\n")
    except yt_dlp.utils.DownloadError as e:
        print(f"⚠️  Skipped {video['id']} — {e}\n")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    videos = fetch_video_ids(CHANNEL_URL, START_VIDEO, END_VIDEO)

    print(f"📥 Starting audio downloads into '{OUTPUT_DIR}/'...\n")
    print("─" * 50)

    for i, video in enumerate(videos, start=1):
        print(f"[{i}/{len(videos)}] ", end="")
        download_audio(video, OUTPUT_DIR)

    print("─" * 50)
    print(f"\n🎉 All done! {len(videos)} audio files saved to '{OUTPUT_DIR}/'")


if __name__ == "__main__":
    main()