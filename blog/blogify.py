import argparse
import os
import re
import yaml
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OUTLINE_PROMPT = (
    "You are an editor planning a blog post from a video transcript. Read the transcript "
    "and produce a concise outline:\n"
    "- One specific, compelling title (not a generic label like 'Introduction to X').\n"
    "- 3-6 descriptive section headings that organize the key themes.\n"
    "- Under each heading, 2-4 bullet points of the key points to cover.\n"
    "- Mark any points best shown as a bulleted list (steps, features, comparisons).\n"
    "- Note 1-3 strong verbatim quotes worth weaving in.\n"
    "Ignore promotional or housekeeping content (sponsor reads, 'subscribe', course/Academy "
    "plugs, sign-offs). Base everything ONLY on the transcript. Output the outline as Markdown."
)

WRITE_PROMPT = (
    "You are an expert blog writer. Using the provided OUTLINE and the original TRANSCRIPT, "
    "write a polished, standalone blog post in Markdown.\n\n"
    "Structure:\n"
    "- Exactly ONE H1 (#) title at the top; every other heading is H2 (##) or H3 (###). "
    "Never use a second H1.\n"
    "- Open with a short hook intro (no 'Introduction' heading needed).\n"
    "- Use descriptive, specific headings — not generic labels like 'Key Features' or 'Conclusion'.\n"
    "- Keep paragraphs to 2-3 sentences. Use bulleted lists for steps, features, or comparisons.\n\n"
    "Voice & content:\n"
    "- Write as a self-contained article. NEVER refer to 'the speaker', 'the video', 'viewers', "
    "or the channel, and omit all sponsor/subscribe/course/sign-off content.\n"
    "- Weave any quotes naturally into the prose; do NOT add a separate 'Quotes' section.\n"
    "- Clean up speech artifacts; remove repetition.\n"
    "- Fidelity: use ONLY information in the transcript. Do not invent facts, numbers, or quotes.\n"
    "- Length: aim for 800-1200 words, but do not pad short source material with filler.\n"
    "- Output ONLY the blog post in Markdown — no preamble or commentary."
)


def generate_post(client, cfg, transcript: str) -> str:
    outline = client.chat.completions.create(
        model=cfg["model"],
        temperature=cfg["temperature"],
        messages=[
            {"role": "system", "content": OUTLINE_PROMPT},
            {"role": "user", "content": transcript},
        ],
    ).choices[0].message.content
    return client.chat.completions.create(
        model=cfg["model"],
        temperature=cfg["temperature"],
        messages=[
            {"role": "system", "content": WRITE_PROMPT},
            {"role": "user", "content": f"OUTLINE:\n{outline}\n\nTRANSCRIPT:\n{transcript}"},
        ],
    ).choices[0].message.content


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


def main():
    parser = argparse.ArgumentParser(description="Generate blog posts from transcripts.")
    parser.add_argument("channel", help="Channel folder name under ./channels/")
    parser.add_argument("--base-dir", default="./channels")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate posts that already exist")
    args = parser.parse_args()

    cfg = load_config()["llm"]
    client = OpenAI(base_url=cfg["base_url"], api_key=os.environ.get("LLM_API_KEY") or os.getenv(cfg.get("api_key_env", "GROQ_API_KEY")))

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
        print(f"[{i}/{len(files)}] Generating {path.name} (outline -> post)...")
        post = generate_post(client, cfg, text)
        out_path.write_text(post, encoding="utf-8")
        print(f"  Saved -> {out_path}")


if __name__ == "__main__":
    main()
