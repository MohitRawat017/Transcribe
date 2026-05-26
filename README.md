# YouTube Audio Fetcher

A Python script that directly fetches audio from YouTube channels. Downloads audio-only files (MP3 format) for a specified range of videos from any YouTube channel.

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install yt-dlp
   ```

2. **Configure the script:**
   Edit `fetcher.py` and update these variables:
   ```python
   CHANNEL_URL = "https://www.youtube.com/@zackdfilms/videos"  # URL of the YouTube channel's videos page
   START_VIDEO  = 1      # index of first video to fetch (1 = most recent)
   END_VIDEO    = 10     # index of last video to fetch
   OUTPUT_DIR   = "./audios"
   ```

3. **Run the script:**
   ```bash
   python fetcher.py
   ```

## Configuration for Different Channels

### To change the channel:
Replace the `CHANNEL_URL` with any YouTube channel's videos page URL:
- Format: `https://www.youtube.com/@username/videos`
- Or: `https://www.youtube.com/channel/CHANNEL_ID/videos`
- Or: `https://www.youtube.com/c/ChannelName/videos`

### To change the video range:
- `START_VIDEO = 1` → Starts from the most recent video
- `END_VIDEO = 50` → Downloads up to the 50th most recent video
- Example: `START_VIDEO = 5, END_VIDEO = 15` → Downloads videos 5 through 15 (most recent to older)

### To change output location:
- `OUTPUT_DIR = "./my_audios"` → Saves to a different folder
- `OUTPUT_DIR = "C:/Users/Name/Documents/audios"` → Absolute path

## What It Does

- **Direct audio fetching** - Downloads only audio, not video
- **MP3 format** - Converts to 128kbps MP3 files
- **Organized output** - Files named by video ID in the specified folder
- **Progress tracking** - Shows download progress for each video

## Notes

- Requires `ffmpeg` installed on your system for audio conversion
- Videos are indexed from most recent (1) to older
- The script skips videos that fail to download and continues with the rest
- All audio files are saved as `{video_id}.mp3` in the output directory