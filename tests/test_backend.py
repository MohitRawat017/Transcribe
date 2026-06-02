import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.jobs import JobStore
from backend.orchestrator import ActiveJobError, PipelineOrchestrator, StageFailure
from blog.auth import BloggerAuthError, auth_status, browser_oauth_disabled, get_service


class JobStoreTests(unittest.TestCase):
    def test_create_and_update_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite")
            job = store.create_job(
                "https://youtube.com/@demo/videos",
                1,
                2,
                str(Path(tmp) / "workspaces" / "demo"),
                workspace_id="demo",
                resumed=True,
            )

            self.assertEqual(job["status"], "queued")
            self.assertEqual(job["stage"], "queued")
            self.assertEqual(job["workspace_id"], "demo")
            self.assertTrue(job["resumed"])

            store.set_running(job["id"])
            store.append_log(job["id"], "hello")
            updated = store.get_job(job["id"])

            self.assertEqual(updated["status"], "running")
            self.assertEqual(updated["stage"], "transcript_api")
            self.assertEqual(updated["logs"], ["hello"])

    def test_active_job_blocks_new_submissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite")
            store.create_job("https://youtube.com/@demo/videos", 1, 1, str(Path(tmp) / "runs"))
            orchestrator = PipelineOrchestrator(tmp, store)

            with self.assertRaises(ActiveJobError):
                orchestrator.submit("https://youtube.com/@other/videos", 1, 1)

    def test_startup_recovery_marks_active_jobs_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs.sqlite")
            job = store.create_job("https://youtube.com/@demo/videos", 1, 1, str(Path(tmp) / "workspaces" / "demo"))

            recovered = store.fail_active_jobs_on_startup("interrupted")
            updated = store.get_job(job["id"])

            self.assertEqual(recovered, 1)
            self.assertFalse(store.has_active_job())
            self.assertEqual(updated["status"], "failed")
            self.assertEqual(updated["stage"], "failed")
            self.assertEqual(updated["error"], "interrupted")
            self.assertIn("interrupted", updated["logs"])


class OrchestratorTests(unittest.TestCase):
    def test_successful_pipeline_uses_isolated_channel_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = JobStore(root / "jobs.sqlite")
            orchestrator = PipelineOrchestrator(root, store)
            job = store.create_job("https://youtube.com/@demo/videos", 1, 1, str(root / "runs" / "job"))
            stages = []

            def fake_run(job_id, stage, _command):
                store.set_stage(job_id, stage)
                store.append_log(job_id, f"stage {stage}")
                stages.append(stage)
                if stage == "transcript_api":
                    channel_dir = root / "workspaces" / "demo" / "channels" / "Demo_Channel"
                    (channel_dir / "transcripts").mkdir(parents=True)

            with patch.object(orchestrator, "_run_command", side_effect=fake_run):
                orchestrator._run(job["id"], "https://youtube.com/@demo/videos", 1, 1, root / "workspaces" / "demo")

            finished = store.get_job(job["id"])
            self.assertEqual(finished["status"], "succeeded")
            self.assertEqual(finished["channel"], "Demo_Channel")
            self.assertEqual(stages, ["transcript_api", "blogify", "blogger_drafts"])

    def test_failed_stage_records_error_and_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = JobStore(root / "jobs.sqlite")
            orchestrator = PipelineOrchestrator(root, store)
            job = store.create_job("https://youtube.com/@demo/videos", 1, 1, str(root / "runs" / "job"))

            def fake_run(job_id, stage, _command):
                store.set_stage(job_id, stage)
                if stage == "transcript_api":
                    channel_dir = root / "workspaces" / "demo" / "channels" / "Demo_Channel"
                    (channel_dir / "transcripts").mkdir(parents=True)
                if stage == "blogify":
                    raise StageFailure("blogify exploded")

            with patch.object(orchestrator, "_run_command", side_effect=fake_run):
                orchestrator._run(job["id"], "https://youtube.com/@demo/videos", 1, 1, root / "workspaces" / "demo")

            failed = store.get_job(job["id"])
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["stage"], "blogify")
            self.assertIn("blogify exploded", failed["error"])


class BloggerAuthTests(unittest.TestCase):
    def test_auth_status_reports_missing_local_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=True):
                status = auth_status(Path(tmp), refresh=False)

        self.assertFalse(status["ready"])
        self.assertFalse(status["has_client_secret"])
        self.assertFalse(status["has_blog_id"])
        self.assertFalse(status["has_token"])
        self.assertFalse(status["has_refresh_token"])
        self.assertEqual(status["last_action"], "missing_token")

    def test_browser_oauth_can_be_disabled_for_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"DISABLE_BROWSER_OAUTH": "1"}, clear=True):
                self.assertTrue(browser_oauth_disabled(Path(tmp)))
                with self.assertRaisesRegex(BloggerAuthError, "Browser OAuth is disabled"):
                    get_service(Path(tmp), interactive=True)


if __name__ == "__main__":
    unittest.main()
