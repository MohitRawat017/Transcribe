import os
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.runtime_check import runtime_report


ROOT = Path(__file__).resolve().parents[1]


class DeploymentConfigTests(unittest.TestCase):
    def test_runtime_report_does_not_include_environment_secrets(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "secret-value"}, clear=False):
            report = runtime_report()

        rendered = repr(report)
        self.assertIn("python", report)
        self.assertIn("ffmpeg", report)
        self.assertIn("deno", report)
        self.assertNotIn("secret-value", rendered)
        self.assertNotIn("GROQ_API_KEY", rendered)

    def test_dockerfile_uses_gpu_web_runtime(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04", dockerfile)
        self.assertIn("DISABLE_BROWSER_OAUTH=1", dockerfile)
        self.assertIn("python -m backend.runtime_check", dockerfile)
        self.assertIn("uvicorn", dockerfile)

    def test_compose_is_private_single_gpu_web_service(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("127.0.0.1:8000:8000", compose)
        self.assertIn("DISABLE_BROWSER_OAUTH", compose)
        self.assertIn("capabilities: [gpu]", compose)
        self.assertNotIn("vllm", compose.lower())

    def test_dockerignore_excludes_runtime_and_generated_paths(self):
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

        for entry in ["runs", "notebooks", "skills", "terminal_output.md", ".env", "frontend/*.tsbuildinfo"]:
            self.assertIn(entry, dockerignore)


if __name__ == "__main__":
    unittest.main()
