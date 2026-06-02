import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yt_dlp

from transcription.youtube_access import (
    BOT_CHECK,
    COOKIE_REJECTED,
    EJS_CHALLENGE,
    NO_FORMATS,
    YoutubeAccessError,
    build_ydl_opts,
    classify_yt_dlp_failure,
    download_with_cookie_retry,
    normalize_channel_url,
)


class YoutubeAccessTests(unittest.TestCase):
    def test_normalize_channel_url_appends_videos(self):
        self.assertEqual(
            normalize_channel_url("https://www.youtube.com/@zackdfilms"),
            "https://www.youtube.com/@zackdfilms/videos",
        )
        self.assertEqual(
            normalize_channel_url("https://www.youtube.com/@zackdfilms/featured"),
            "https://www.youtube.com/@zackdfilms/videos",
        )
        self.assertEqual(
            normalize_channel_url("https://www.youtube.com/@zackdfilms/videos"),
            "https://www.youtube.com/@zackdfilms/videos",
        )

    def test_build_ydl_opts_includes_deno_and_sleep_without_cookies_by_default(self):
        with patch.dict(os.environ, {"YTDLP_SLEEP_MIN": "2", "YTDLP_SLEEP_MAX": "5"}, clear=True):
            opts = build_ydl_opts()

        self.assertEqual(opts["js_runtimes"], ["deno"])
        self.assertEqual(opts["sleep_interval"], 2)
        self.assertEqual(opts["max_sleep_interval"], 5)
        self.assertNotIn("cookiefile", opts)

    def test_build_ydl_opts_adds_cookiefile_only_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            with patch.dict(os.environ, {"YTDLP_COOKIE_PATH": str(cookie_file)}, clear=True):
                self.assertNotIn("cookiefile", build_ydl_opts(use_cookies=False))
                self.assertEqual(build_ydl_opts(use_cookies=True)["cookiefile"], str(cookie_file))

    def test_classify_common_failures(self):
        self.assertEqual(classify_yt_dlp_failure("Sign in to confirm you're not a bot"), BOT_CHECK)
        self.assertEqual(classify_yt_dlp_failure("n challenge solving failed"), EJS_CHALLENGE)
        self.assertEqual(classify_yt_dlp_failure("Requested format is not available"), NO_FORMATS)
        self.assertEqual(classify_yt_dlp_failure("cookies are no longer valid"), COOKIE_REJECTED)

    def test_audio_download_retries_with_cookies_after_bot_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            calls = []

            class FakeYDL:
                def __init__(self, opts):
                    self.opts = opts
                    calls.append(opts)

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def download(self, _urls):
                    if len(calls) == 1:
                        raise yt_dlp.utils.DownloadError("ERROR: Sign in to confirm you're not a bot")

            with patch.dict(os.environ, {"YTDLP_COOKIE_PATH": str(cookie_file), "YTDLP_USE_COOKIES": "auto"}, clear=True):
                with patch("transcription.youtube_access.yt_dlp.YoutubeDL", FakeYDL):
                    mode = download_with_cookie_retry(["https://www.youtube.com/watch?v=test"], {}, "audio download")

            self.assertEqual(mode, "yt-dlp:cookies")
            self.assertNotIn("cookiefile", calls[0])
            self.assertEqual(calls[1]["cookiefile"], str(cookie_file))

    def test_audio_download_does_not_retry_ejs_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            calls = []

            class FakeYDL:
                def __init__(self, opts):
                    calls.append(opts)

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def download(self, _urls):
                    raise yt_dlp.utils.DownloadError("ERROR: n challenge solving failed")

            with patch.dict(os.environ, {"YTDLP_COOKIE_PATH": str(cookie_file), "YTDLP_USE_COOKIES": "auto"}, clear=True):
                with patch("transcription.youtube_access.yt_dlp.YoutubeDL", FakeYDL):
                    with self.assertRaises(YoutubeAccessError):
                        download_with_cookie_retry(["https://www.youtube.com/watch?v=test"], {}, "audio download")

            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
