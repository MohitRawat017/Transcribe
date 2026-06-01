import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blog import publish


class FakeInsert:
    def __init__(self, post_id: str):
        self.post_id = post_id

    def execute(self):
        return {"id": self.post_id}


class FakePosts:
    def __init__(self):
        self.calls = []

    def insert(self, **kwargs):
        self.calls.append(kwargs)
        return FakeInsert(f"post-{len(self.calls)}")


class FakeService:
    def __init__(self):
        self._posts = FakePosts()

    def posts(self):
        return self._posts


class PublishTests(unittest.TestCase):
    def test_publish_ledger_skips_already_published_posts(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            blog_dir = base / "Demo_Channel" / "blogs"
            blog_dir.mkdir(parents=True)
            (blog_dir / "one.md").write_text("# One\n\nBody", encoding="utf-8")
            service = FakeService()

            with (
                patch.object(publish, "get_service", return_value=service),
                patch.object(publish, "get_blog_id", return_value="blog-id"),
                patch.object(publish.time, "sleep", return_value=None),
            ):
                first = publish.publish_blogs("Demo_Channel", str(base), draft=True)
                second = publish.publish_blogs("Demo_Channel", str(base), draft=True)

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertEqual(len(service.posts().calls), 1)


if __name__ == "__main__":
    unittest.main()
