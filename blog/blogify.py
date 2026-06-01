import argparse
import os
import re
import time
import yaml
from pathlib import Path

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

load_dotenv()

POST_PROMPT = (
    "You are an expert blog writer. Convert the provided video transcript into a polished, "
    "standalone blog post in Markdown. Silently plan the title and sections first, but output "
    "only the final article.\n\n"
    "Structure:\n"
    "- Exactly ONE H1 (#) title at the top; every other heading is H2 (##) or H3 (###). "
    "Never use a second H1.\n"
    "- Open with a short hook intro (no 'Introduction' heading needed).\n"
    "- Use descriptive, specific headings, not generic labels like 'Key Features' or 'Conclusion'.\n"
    "- Keep paragraphs to 2-3 sentences. Use bulleted lists for steps, features, or comparisons.\n\n"
    "Voice & content:\n"
    "- Write as a self-contained article. NEVER refer to 'the speaker', 'the video', 'viewers', "
    "or the channel, and omit all sponsor/subscribe/course/sign-off content.\n"
    "- Weave 1-3 strong verbatim quotes naturally into the prose if the transcript contains them; "
    "do NOT add a separate 'Quotes' section.\n"
    "- Clean up speech artifacts; remove repetition.\n"
    "- Fidelity: use ONLY information in the transcript. Do not invent facts, numbers, or quotes.\n"
    "- Length: aim for 800-1200 words, but do not pad short source material with filler.\n"
    "- Output ONLY the blog post in Markdown, no preamble or commentary."
)


def load_config(path="config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def clean_transcript(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        line = re.sub(r"^\[[^\]]*\]\s*", "", line)  # strip "[12.3s] " / "[1.0s -> 3.5s] "
        if line.strip():
            lines.append(line.strip())
    return "\n".join(lines)


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (RateLimitError, APIConnectionError, APITimeoutError)):
        return True
    status_code = getattr(exc, "status_code", None)
    return isinstance(exc, APIStatusError) and status_code in {429, 500, 502, 503, 504}


def create_with_retry(client, cfg, transcript: str):
    retries = int(cfg.get("max_retries", 4))
    delay = float(cfg.get("retry_delay", 2))
    for attempt in range(1, retries + 1):
        try:
            return client.chat.completions.create(
                model=cfg["model"],
                temperature=cfg["temperature"],
                messages=[
                    {"role": "system", "content": POST_PROMPT},
                    {"role": "user", "content": transcript},
                ],
            )
        except Exception as exc:
            if attempt == retries or not is_retryable(exc):
                raise
            print(f"  LLM transient error ({type(exc).__name__}), retrying in {delay:.1f}s...")
            time.sleep(delay)
            delay *= 2


def usage_summary(usage) -> str:
    if usage is None:
        return "usage unavailable"
    if hasattr(usage, "model_dump"):
        data = usage.model_dump()
    elif isinstance(usage, dict):
        data = usage
    else:
        data = {key: getattr(usage, key, None) for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    tokens = [f"{key}={value}" for key, value in data.items() if value is not None]
    return ", ".join(tokens) if tokens else "usage unavailable"


def generate_post(client, cfg, transcript: str) -> tuple[str, object | None]:
    response = create_with_retry(client, cfg, transcript)
    return response.choices[0].message.content, getattr(response, "usage", None)


def main():
    parser = argparse.ArgumentParser(description="Generate blog posts from transcripts.")
    parser.add_argument("channel", help="Channel folder name under ./channels/")
    parser.add_argument("--base-dir", default="./channels")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate posts that already exist")
    args = parser.parse_args()

    cfg = load_config()["llm"]
    client = OpenAI(
        base_url=cfg["base_url"],
        api_key=os.environ.get("LLM_API_KEY") or os.getenv(cfg.get("api_key_env", "GROQ_API_KEY")) or cfg.get("api_key"),
    )

    transcript_dir = Path(args.base_dir) / args.channel / "transcripts"
    blog_dir = Path(args.base_dir) / args.channel / "blogs"
    blog_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(transcript_dir.glob("*.txt"))
    print(f"Found {len(files)} transcripts.")
    for i, path in enumerate(files, 1):
        out_path = blog_dir / (path.stem + ".md")
        if out_path.exists() and not args.overwrite:
            print(f"[{i}/{len(files)}] Skipping {path.name} (already done)")
            continue
        text = clean_transcript(path.read_text(encoding="utf-8"))
        print(f"[{i}/{len(files)}] Generating {path.name} (one-pass post)...")
        print(f"  Input size: {len(text)} chars, {len(text.split())} words")
        post, usage = generate_post(client, cfg, text)
        out_path.write_text(post, encoding="utf-8")
        print(f"  LLM usage: {usage_summary(usage)}")
        print(f"  Saved -> {out_path}")


if __name__ == "__main__":
    main()
