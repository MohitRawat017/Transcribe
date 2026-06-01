import types
import unittest

from blog.blogify import generate_post, usage_summary


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = types.SimpleNamespace(content="# Title\n\nBody")
        choice = types.SimpleNamespace(message=message)
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        return types.SimpleNamespace(choices=[choice], usage=usage)


class FakeClient:
    def __init__(self):
        self.completions = FakeCompletions()
        self.chat = types.SimpleNamespace(completions=self.completions)


class BlogifyTests(unittest.TestCase):
    def test_generate_post_uses_one_model_call(self):
        client = FakeClient()
        post, usage = generate_post(client, {"model": "demo", "temperature": 0.2}, "transcript")

        self.assertEqual(post, "# Title\n\nBody")
        self.assertEqual(len(client.completions.calls), 1)
        messages = client.completions.calls[0]["messages"]
        self.assertEqual(len(messages), 2)
        self.assertNotIn("OUTLINE:", messages[1]["content"])
        self.assertEqual(usage_summary(usage), "prompt_tokens=10, completion_tokens=5, total_tokens=15")


if __name__ == "__main__":
    unittest.main()
