import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Any

import yt_dlp


BOT_CHECK = "bot_check"
COOKIE_REJECTED = "cookie_rejected"
EJS_CHALLENGE = "ejs_challenge"
NO_FORMATS = "no_formats"
UNAVAILABLE_VIDEO = "unavailable_video"
UNKNOWN = "unknown"


class YoutubeAccessError(RuntimeError):
    def __init__(self, message: str, reason: str = UNKNOWN):
        super().__init__(message)
        self.reason = reason


def slugify(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name).strip("_") or "unknown_channel"


def normalize_channel_url(channel_url: str) -> str:
    url = channel_url.strip()
    if not url:
        return url
    bare = url.rstrip("/")
    if re.search(r"/(videos|streams|shorts|featured|playlists|community|about)$", bare):
        return bare if bare.endswith("/videos") else f"{bare.rsplit('/', 1)[0]}/videos"
    if "youtube.com/" in bare and "watch?" not in bare and "/playlist" not in bare:
        return f"{bare}/videos"
    return bare


def cookie_path() -> Path | None:
    value = os.environ.get("YTDLP_COOKIE_PATH", "").strip()
    return Path(value) if value else None


def has_cookie_file() -> bool:
    path = cookie_path()
    return bool(path and path.exists())


def deno_available() -> bool:
    return shutil.which("deno") is not None


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def build_ydl_opts(
    *,
    use_cookies: bool = False,
    quiet: bool = True,
    no_warnings: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sleep_min = max(0, _env_int("YTDLP_SLEEP_MIN", 3))
    sleep_max = max(sleep_min, _env_int("YTDLP_SLEEP_MAX", 6))
    opts: dict[str, Any] = {
        "quiet": quiet,
        "no_warnings": no_warnings,
        "sleep_interval": sleep_min,
        "max_sleep_interval": sleep_max,
        "js_runtimes": ["deno"],
    }

    user_agent = os.environ.get("YTDLP_USER_AGENT", "").strip()
    if user_agent:
        opts["http_headers"] = {"User-Agent": user_agent}

    path = cookie_path()
    if use_cookies and path and path.exists():
        opts["cookiefile"] = str(path)

    if extra:
        opts.update(extra)
    return opts


def classify_yt_dlp_failure(value: object) -> str:
    text = str(value).lower()
    if "cookie" in text and any(token in text for token in ("expired", "invalid", "rejected", "no longer valid")):
        return COOKIE_REJECTED
    if any(token in text for token in ("sign in to confirm", "confirm you're not a bot", "automated requests")):
        return BOT_CHECK
    if any(token in text for token in ("n challenge solving failed", "no supported javascript runtime", "challenge solver", "yt-dlp-ejs", "ejs")):
        return EJS_CHALLENGE
    if any(token in text for token in ("requested format is not available", "only images are available", "no video formats")):
        return NO_FORMATS
    if any(token in text for token in ("video unavailable", "this video is unavailable", "private video")):
        return UNAVAILABLE_VIDEO
    return UNKNOWN


def should_retry_with_cookies(reason: str) -> bool:
    mode = os.environ.get("YTDLP_USE_COOKIES", "auto").strip().lower()
    if mode in {"0", "false", "never", "none", "off"}:
        return False
    if not has_cookie_file():
        return False
    if mode in {"1", "true", "always", "on"}:
        return True
    return reason in {BOT_CHECK, NO_FORMATS}


def extract_info_with_cookie_retry(url: str, extra_opts: dict[str, Any], label: str) -> tuple[dict[str, Any], str]:
    try:
        with yt_dlp.YoutubeDL(build_ydl_opts(use_cookies=False, extra=extra_opts)) as ydl:
            return ydl.extract_info(url, download=False), "yt-dlp:no-cookies"
    except yt_dlp.utils.DownloadError as exc:
        reason = classify_yt_dlp_failure(exc)
        if should_retry_with_cookies(reason):
            print(f"{label}: no-cookie yt-dlp failed ({reason}); retrying with cookies.")
            try:
                with yt_dlp.YoutubeDL(build_ydl_opts(use_cookies=True, extra=extra_opts)) as ydl:
                    return ydl.extract_info(url, download=False), "yt-dlp:cookies"
            except yt_dlp.utils.DownloadError as cookie_exc:
                cookie_reason = classify_yt_dlp_failure(cookie_exc)
                raise YoutubeAccessError(f"{label} failed with cookies: {cookie_reason}: {cookie_exc}", cookie_reason) from cookie_exc
        raise YoutubeAccessError(f"{label} failed: {reason}: {exc}", reason) from exc


def download_with_cookie_retry(urls: list[str], extra_opts: dict[str, Any], label: str) -> str:
    try:
        with yt_dlp.YoutubeDL(build_ydl_opts(use_cookies=False, extra=extra_opts)) as ydl:
            ydl.download(urls)
        return "yt-dlp:no-cookies"
    except yt_dlp.utils.DownloadError as exc:
        reason = classify_yt_dlp_failure(exc)
        if should_retry_with_cookies(reason):
            print(f"  {label}: no-cookie yt-dlp failed ({reason}); retrying with cookies.")
            try:
                with yt_dlp.YoutubeDL(build_ydl_opts(use_cookies=True, extra=extra_opts)) as ydl:
                    ydl.download(urls)
                return "yt-dlp:cookies"
            except yt_dlp.utils.DownloadError as cookie_exc:
                cookie_reason = classify_yt_dlp_failure(cookie_exc)
                raise YoutubeAccessError(f"{label} failed with cookies: {cookie_reason}: {cookie_exc}", cookie_reason) from cookie_exc
        raise YoutubeAccessError(f"{label} failed: {reason}: {exc}", reason) from exc


def resolve_channel_workspace(channel_url: str) -> dict[str, str]:
    normalized_url = normalize_channel_url(channel_url)
    info, _mode = extract_info_with_cookie_retry(
        normalized_url,
        {"extract_flat": "in_playlist", "yes_playlist": True, "playlistend": 1, "ignoreerrors": True},
        "channel metadata",
    )
    if not info:
        raise YoutubeAccessError("Could not resolve channel metadata. Check the URL.")

    channel_name = slugify(info.get("channel") or info.get("uploader") or info.get("title") or "unknown_channel")
    channel_id = info.get("channel_id") or info.get("uploader_id")
    workspace_id = slugify(channel_id) if channel_id else hashlib.sha1(normalized_url.encode("utf-8")).hexdigest()[:16]
    return {"workspace_id": workspace_id, "channel": channel_name, "normalized_url": normalized_url}
