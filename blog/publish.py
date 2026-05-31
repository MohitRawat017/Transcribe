import argparse
import os
import time
import markdown
from pathlib import Path
from dotenv import load_dotenv
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()
SCOPES = ["https://www.googleapis.com/auth/blogger"]


def get_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("client_secret.json", SCOPES)
            creds = flow.run_local_server(port=0)
        Path("token.json").write_text(creds.to_json())
    return build("blogger", "v3", credentials=creds)


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


def main():
    parser = argparse.ArgumentParser(description="Publish blog posts to Blogger.")
    parser.add_argument("channel", nargs="?", help="Channel folder name under ./channels/")
    parser.add_argument("--base-dir", default="./channels")
    parser.add_argument("--draft", action="store_true", help="Publish as draft instead of live")
    parser.add_argument("--list-blogs", action="store_true", help="List your blogs and their IDs, then exit")
    args = parser.parse_args()

    service = get_service()

    if args.list_blogs:
        blogs = service.blogs().listByUser(userId="self").execute().get("items", [])
        for b in blogs:
            print(f"{b['id']}  {b['name']}  ({b['url']})")
        return

    if not args.channel:
        parser.error("channel is required unless --list-blogs is used")
    blog_id = os.environ["BLOGGER_BLOG_ID"]

    blog_dir = Path(args.base_dir) / args.channel / "blogs"
    files = sorted(blog_dir.glob("*.md"))
    print(f"Found {len(files)} posts.")
    for i, path in enumerate(files, 1):
        title, html = md_to_post(path.read_text(encoding="utf-8"))
        print(f"[{i}/{len(files)}] Publishing: {title}")
        insert_with_retry(service, blog_id, {"title": title, "content": html}, args.draft)
        print("  Done")
        time.sleep(2)  # be gentle with Blogger's write rate limit


if __name__ == "__main__":
    main()
