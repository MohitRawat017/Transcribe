import hashlib
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yt_dlp

from backend.jobs import JobStore


class ActiveJobError(RuntimeError):
    pass


class StageFailure(RuntimeError):
    pass


def slugify(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name).strip("_") or "unknown_channel"


def resolve_channel_workspace(channel_url: str) -> dict:
    ydl_opts = {"quiet": True, "extract_flat": True, "playlistend": 1, "ignoreerrors": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    if not info:
        raise StageFailure("Could not resolve channel metadata. Check the URL.")

    channel_name = slugify(info.get("channel") or info.get("uploader") or info.get("title") or "unknown_channel")
    channel_id = info.get("channel_id") or info.get("uploader_id")
    workspace_id = slugify(channel_id) if channel_id else hashlib.sha1(channel_url.encode("utf-8")).hexdigest()[:16]
    return {"workspace_id": workspace_id, "channel": channel_name}


class PipelineOrchestrator:
    def __init__(self, repo_root: str | Path, store: JobStore):
        self.repo_root = Path(repo_root).resolve()
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=1)

    def submit(self, channel_url: str, start: int, end: int) -> dict:
        if self.store.has_active_job():
            raise ActiveJobError("Another job is already running.")

        workspace = resolve_channel_workspace(channel_url)
        workspace_dir = self.repo_root / "workspaces" / workspace["workspace_id"]
        resumed = workspace_dir.exists()
        job = self.store.create_job(
            channel_url,
            start,
            end,
            str(workspace_dir),
            workspace_id=workspace["workspace_id"],
            resumed=resumed,
        )
        self.store.set_channel(job["id"], workspace["channel"])
        self.executor.submit(self._run, job["id"], channel_url, start, end, workspace_dir)
        return self.store.get_job(job["id"])

    def _run(self, job_id: str, channel_url: str, start: int, end: int, workspace_dir: Path) -> None:
        self.store.set_running(job_id)
        channels_dir = workspace_dir / "channels"

        try:
            if workspace_dir.exists():
                self.store.append_log(job_id, f"Resuming workspace: {workspace_dir}")
            else:
                self.store.append_log(job_id, f"Creating workspace: {workspace_dir}")

            transcribe_cmd = [
                sys.executable,
                "-u",
                str(self.repo_root / "transcription" / "transcribe.py"),
                channel_url,
                "--start",
                str(start),
                "--end",
                str(end),
                "--base-dir",
                str(channels_dir),
            ]
            self._run_command(job_id, "transcript_api", transcribe_cmd)

            channel = self._discover_channel(channels_dir)
            self.store.set_channel(job_id, channel)

            blogify_cmd = [
                sys.executable,
                "-u",
                str(self.repo_root / "blog" / "blogify.py"),
                channel,
                "--base-dir",
                str(channels_dir),
            ]
            self._run_command(job_id, "blogify", blogify_cmd)

            publish_cmd = [
                sys.executable,
                "-u",
                str(self.repo_root / "blog" / "publish.py"),
                channel,
                "--base-dir",
                str(channels_dir),
                "--draft",
                "--ledger-path",
                str(channels_dir / channel / "published.json"),
            ]
            self._run_command(job_id, "blogger_drafts", publish_cmd)
            self.store.append_log(job_id, "Pipeline completed. Blogger drafts are ready.")
            self.store.complete(job_id)
        except Exception as exc:
            self.store.append_log(job_id, f"Pipeline failed: {exc}")
            self.store.fail(job_id, str(exc))

    def _run_command(self, job_id: str, stage: str, command: list[str]) -> None:
        self.store.set_stage(job_id, stage)
        self.store.append_log(job_id, f"Starting stage: {stage}")

        process = subprocess.Popen(
            command,
            cwd=self.repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if not line:
                continue
            if "API failed, falling back to Whisper" in line:
                self.store.set_stage(job_id, "whisper_fallback")
            self.store.append_log(job_id, line)

        code = process.wait()
        if code != 0:
            raise StageFailure(f"{stage} exited with code {code}")

    def _discover_channel(self, channels_dir: Path) -> str:
        if not channels_dir.exists():
            raise StageFailure("Transcription did not create a channels directory.")
        channels = sorted(path.name for path in channels_dir.iterdir() if path.is_dir())
        if len(channels) != 1:
            raise StageFailure(f"Expected one channel output, found {len(channels)}.")
        return channels[0]
