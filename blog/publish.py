import argparse
import json
import time
import markdown
from pathlib import Path
from dotenv import load_dotenv
from googleapiclient.errors import HttpError
import sys

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from blog.auth import get_blog_id, get_service

load_dotenv()


def md_to_post(text: str):
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), "Untitled")
    return title, markdown.markdown(text)


def insert_with_retry(service, blog_id, body, is_draft, retries=5):
    delay = 5
    for attempt in range(retries):
        try:
            return service.posts().insert(blogId=blog_id, isDraft=is_draft, body=body).execute()
        except HttpError as e:
            if e.resp.status == 429 and attempt < retries - 1:
                print(f"  Rate limited, retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2
            else:
                raise


def load_ledger(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_ledger(path: Path, ledger: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2, sort_keys=True), encoding="utf-8")


def publish_blogs(channel: str, base_dir: str = "./channels", draft: bool = False, ledger_path: str | None = None) -> int:
    service = get_service(require_blog_id=True)
    blog_id = get_blog_id()

    blog_dir = Path(base_dir) / channel / "blogs"
    ledger_file = Path(ledger_path) if ledger_path else Path(base_dir) / channel / "published.json"
    ledger = load_ledger(ledger_file)
    files = sorted(blog_dir.glob("*.md"))
    print(f"Found {len(files)} posts.")
    published = 0
    for i, path in enumerate(files, 1):
        if path.name in ledger:
            print(f"[{i}/{len(files)}] Skipping {path.name} (already published as {ledger[path.name]})")
            continue
        title, html = md_to_post(path.read_text(encoding="utf-8"))
        print(f"[{i}/{len(files)}] Publishing: {title}")
        result = insert_with_retry(service, blog_id, {"title": title, "content": html}, draft)
        ledger[path.name] = result.get("id", "")
        save_ledger(ledger_file, ledger)
        published += 1
        print("  Done")
        time.sleep(2)  # be gentle with Blogger's write rate limit
    return published


def main():
    parser = argparse.ArgumentParser(description="Publish blog posts to Blogger.")
    parser.add_argument("channel", nargs="?", help="Channel folder name under ./channels/")
    parser.add_argument("--base-dir", default="./channels")
    parser.add_argument("--draft", action="store_true", help="Publish as draft instead of live")
    parser.add_argument("--ledger-path", default=None, help="Path to published-post ledger JSON")
    parser.add_argument("--list-blogs", action="store_true", help="List your blogs and their IDs, then exit")
    args = parser.parse_args()

    service = get_service(require_blog_id=False)

    if args.list_blogs:
        blogs = service.blogs().listByUser(userId="self").execute().get("items", [])
        for b in blogs:
            print(f"{b['id']}  {b['name']}  ({b['url']})")
        return

    if not args.channel:
        parser.error("channel is required unless --list-blogs is used")
    publish_blogs(args.channel, args.base_dir, args.draft, args.ledger_path)


if __name__ == "__main__":
    main()
