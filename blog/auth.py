import os
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/blogger"]


class BloggerAuthError(RuntimeError):
    pass


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _root(root: str | Path | None = None) -> Path:
    return Path(root or ".").resolve()


def _paths(root: Path) -> tuple[Path, Path]:
    return root / "client_secret.json", root / "token.json"


def _load_env(root: Path) -> None:
    load_dotenv(root / ".env")


def browser_oauth_disabled(root: str | Path | None = None) -> bool:
    repo_root = _root(root)
    _load_env(repo_root)
    return _truthy(os.environ.get("DISABLE_BROWSER_OAUTH"))


def get_blog_id(root: str | Path | None = None) -> str:
    repo_root = _root(root)
    _load_env(repo_root)
    blog_id = os.environ.get("BLOGGER_BLOG_ID")
    if not blog_id:
        raise BloggerAuthError("BLOGGER_BLOG_ID is not set.")
    return blog_id


def auth_status(root: str | Path | None = None, refresh: bool = True) -> dict:
    repo_root = _root(root)
    _load_env(repo_root)
    client_secret_path, token_path = _paths(repo_root)

    has_client_secret = client_secret_path.exists()
    has_blog_id = bool(os.environ.get("BLOGGER_BLOG_ID"))
    has_token = token_path.exists()
    has_refresh_token = False
    token_valid = False
    expiry = None
    last_action = "missing_token"
    message = "Blogger is ready."

    if has_token:
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            has_refresh_token = bool(creds.refresh_token)
            expiry = creds.expiry.isoformat() if creds.expiry else None
            if creds.valid:
                token_valid = True
                last_action = "valid"
            elif refresh and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")
                token_valid = True
                expiry = creds.expiry.isoformat() if creds.expiry else None
                last_action = "refreshed"
            else:
                last_action = "needs_reconnect"
                message = "Blogger token is missing, expired, or needs reauthorization."
        except Exception as exc:
            last_action = "error"
            message = f"Blogger token could not be read: {exc}"
    else:
        message = "Blogger token has not been generated yet."

    if not has_client_secret:
        message = "client_secret.json is missing."
    elif not has_blog_id:
        message = "BLOGGER_BLOG_ID is not set."

    ready = has_client_secret and has_blog_id and token_valid
    if ready:
        message = "Blogger credentials and token are ready."

    return {
        "ready": ready,
        "has_client_secret": has_client_secret,
        "has_blog_id": has_blog_id,
        "has_token": has_token,
        "has_refresh_token": has_refresh_token,
        "token_valid": token_valid,
        "expiry": expiry,
        "last_action": last_action,
        "message": message,
    }


def get_service(
    root: str | Path | None = None,
    *,
    interactive: bool = True,
    require_blog_id: bool = False,
    force_reconnect: bool = False,
):
    repo_root = _root(root)
    _load_env(repo_root)
    client_secret_path, token_path = _paths(repo_root)

    creds = None
    if token_path.exists() and not force_reconnect:
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif interactive:
            if browser_oauth_disabled(repo_root):
                raise BloggerAuthError(
                    "Browser OAuth is disabled in production. Generate token.json locally, upload it to the server, "
                    "then use Check token."
                )
            if not client_secret_path.exists():
                raise BloggerAuthError("client_secret.json is missing.")
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
            creds = flow.run_local_server(port=0, prompt="consent")
        else:
            raise BloggerAuthError("Blogger token is missing or invalid.")
        token_path.write_text(creds.to_json(), encoding="utf-8")

    if require_blog_id:
        get_blog_id(repo_root)

    return build("blogger", "v3", credentials=creds)


def refresh_blogger(root: str | Path | None = None) -> dict:
    return auth_status(root, refresh=True)


def connect_blogger(root: str | Path | None = None, force_reconnect: bool = False) -> dict:
    repo_root = _root(root)
    service = get_service(repo_root, interactive=True, require_blog_id=False, force_reconnect=force_reconnect)
    service.blogs().listByUser(userId="self").execute()
    status = auth_status(repo_root, refresh=True)
    if force_reconnect:
        status["last_action"] = "reconnected"
    return status
