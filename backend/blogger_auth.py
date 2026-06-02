from pathlib import Path

from blog.auth import auth_status, browser_oauth_disabled, connect_blogger, refresh_blogger


def get_status(repo_root: Path) -> dict:
    return auth_status(repo_root, refresh=True)


def connect(repo_root: Path) -> dict:
    return connect_blogger(repo_root)


def refresh(repo_root: Path) -> dict:
    return refresh_blogger(repo_root)


def reconnect(repo_root: Path) -> dict:
    return connect_blogger(repo_root, force_reconnect=True)


def oauth_disabled(repo_root: Path) -> bool:
    return browser_oauth_disabled(repo_root)
