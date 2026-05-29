import argparse
import os
import re
import sys
import yt_dlp


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

    print(f"Scanning channel (videos {start}-{'all' if end is None else end})...")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    if not info or "entries" not in info:
        print("Error: could not fetch channel info. Check the URL.")
        sys.exit(1)

    videos = [
        {"id": e["id"], "title": e.get("title", "Unknown")}
        for e in info["entries"]
        if e and e.get("id") and not e["id"].startswith("UC")
    ]
    print(f"Found {len(videos)} videos.\n")
    return videos


def download_audio(video: dict, output_dir: str) -> None:
    # check for any already-downloaded format
    for ext in ("opus", "ogg", "webm", "m4a", "mp3"):
        if os.path.exists(os.path.join(output_dir, f"{video['id']}.{ext}")):
            print(f"  Already exists, skipping: {video['id']}\n")
            return

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(output_dir, "%(id)s.%(ext)s"),
        "quiet": False,
        "no_warnings": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "opus",
            "preferredquality": "64",
        }],
        "postprocessor_args": ["-ac", "1"],
    }

    print(f"Downloading: {video['title']}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video['id']}"])
        print(f"  Done: {video['id']}.opus\n")
    except yt_dlp.utils.DownloadError as e:
        print(f"  Skipped {video['id']}: {e}\n")


def main():
    parser = argparse.ArgumentParser(description="Fetch audio from a YouTube channel.")
    parser.add_argument("channel_url", help="YouTube channel videos URL")
    parser.add_argument("--start", type=int, default=1, help="Start index (default: 1)")
    parser.add_argument("--end", type=int, default=None, help="End index (default: all)")
    parser.add_argument("--output-dir", default="./channels", help="Base output directory (default: ./channels)")
    args = parser.parse_args()

    channel_name = slugify(get_channel_name(args.channel_url))
    output_dir = os.path.join(args.output_dir, channel_name, "audios")
    os.makedirs(output_dir, exist_ok=True)

    videos = fetch_video_ids(args.channel_url, args.start, args.end)

    print(f"Saving audio to '{output_dir}/'...")
    print("-" * 60)
    for i, video in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] ", end="")
        download_audio(video, output_dir)

    print("-" * 60)
    print(f"Done. {len(videos)} files in '{output_dir}/'")


if __name__ == "__main__":
    main()
