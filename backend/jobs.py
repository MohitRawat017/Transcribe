import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


ACTIVE_STATUSES = ("queued", "running")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    channel_url TEXT NOT NULL,
                    workspace_id TEXT,
                    resumed INTEGER NOT NULL DEFAULT 0,
                    channel TEXT,
                    start_index INTEGER NOT NULL,
                    end_index INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    logs TEXT NOT NULL,
                    error TEXT,
                    output_dir TEXT
                )
                """
            )
            existing = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            if "workspace_id" not in existing:
                conn.execute("ALTER TABLE jobs ADD COLUMN workspace_id TEXT")
            if "resumed" not in existing:
                conn.execute("ALTER TABLE jobs ADD COLUMN resumed INTEGER NOT NULL DEFAULT 0")

    def create_job(
        self,
        channel_url: str,
        start: int,
        end: int,
        output_dir: str,
        workspace_id: str | None = None,
        resumed: bool = False,
    ) -> dict:
        job_id = uuid.uuid4().hex
        timestamp = _now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, status, stage, channel_url, workspace_id, resumed, channel, start_index, end_index,
                    created_at, updated_at, logs, error, output_dir
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    "queued",
                    "queued",
                    channel_url,
                    workspace_id,
                    1 if resumed else 0,
                    None,
                    start,
                    end,
                    timestamp,
                    timestamp,
                    "[]",
                    None,
                    output_dir,
                ),
            )
        return self.get_job(job_id)

    def has_active_job(self) -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE status IN (?, ?) LIMIT 1",
                ACTIVE_STATUSES,
            ).fetchone()
            return row is not None

    def fail_active_jobs_on_startup(self, message: str = "Server restarted before this job completed.") -> int:
        timestamp = _now()
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, logs FROM jobs WHERE status IN (?, ?)",
                ACTIVE_STATUSES,
            ).fetchall()
            for row in rows:
                logs = json.loads(row["logs"])
                logs.append(message)
                conn.execute(
                    """
                    UPDATE jobs
                    SET status = ?, stage = ?, logs = ?, error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    ("failed", "failed", json.dumps(logs), message, timestamp, row["id"]),
                )
            return len(rows)

    def set_running(self, job_id: str) -> None:
        self._update(job_id, status="running", stage="transcript_api")

    def set_stage(self, job_id: str, stage: str) -> None:
        self._update(job_id, stage=stage)

    def set_channel(self, job_id: str, channel: str) -> None:
        self._update(job_id, channel=channel)

    def set_output_dir(self, job_id: str, output_dir: str) -> None:
        self._update(job_id, output_dir=output_dir)

    def complete(self, job_id: str) -> None:
        self._update(job_id, status="succeeded", stage="succeeded", error=None)

    def fail(self, job_id: str, error: str) -> None:
        self._update(job_id, status="failed", error=error)

    def append_log(self, job_id: str, line: str) -> None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT logs FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return
            logs = json.loads(row["logs"])
            logs.append(line)
            conn.execute(
                "UPDATE jobs SET logs = ?, updated_at = ? WHERE id = ?",
                (json.dumps(logs), _now(), job_id),
            )

    def get_job(self, job_id: str) -> dict | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def _update(self, job_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values())
        values.append(job_id)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)

    def _row_to_job(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "status": row["status"],
            "stage": row["stage"],
            "channel_url": row["channel_url"],
            "workspace_id": row["workspace_id"],
            "resumed": bool(row["resumed"]),
            "channel": row["channel"],
            "start": row["start_index"],
            "end": row["end_index"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "logs": json.loads(row["logs"]),
            "error": row["error"],
            "output_dir": row["output_dir"],
        }
