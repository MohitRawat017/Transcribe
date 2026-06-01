from pathlib import Path

from blog.auth import auth_status, connect_blogger


def get_status(repo_root: Path) -> dict:
    return auth_status(repo_root, refresh=True)


def connect(repo_root: Path) -> dict:
    return connect_blogger(repo_root)
