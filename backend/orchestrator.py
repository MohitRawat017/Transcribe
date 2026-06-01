import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from backend.jobs import JobStore


class ActiveJobError(RuntimeError):
    pass


class StageFailure(RuntimeError):
    pass


class PipelineOrchestrator:
    def __init__(self, repo_root: str | Path, store: JobStore):
        self.repo_root = Path(repo_root).resolve()
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=1)

    def submit(self, channel_url: str, start: int, end: int) -> dict:
        if self.store.has_active_job():
            raise ActiveJobError("Another job is already running.")

        output_dir = self.repo_root / "runs" / "pending"
        job = self.store.create_job(channel_url, start, end, str(output_dir))
        job_output_dir = self.repo_root / "runs" / job["id"]
        self.store.set_output_dir(job["id"], str(job_output_dir))
        self.executor.submit(self._run, job["id"], channel_url, start, end)
        return self.store.get_job(job["id"])

    def _run(self, job_id: str, channel_url: str, start: int, end: int) -> None:
        self.store.set_running(job_id)
        run_dir = self.repo_root / "runs" / job_id
        channels_dir = run_dir / "channels"

        try:
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
