import argparse
import os
import yaml
import torch
import whisper
from pathlib import Path


def load_config(path: str = "config.yaml") -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return yaml.safe_load(f)
    return {}


def main():
    cfg = load_config()

    parser = argparse.ArgumentParser(description="Transcribe audio files using Whisper.")
    parser.add_argument("channel", help="Channel folder name under ./channels/")
    parser.add_argument("--base-dir", default="./channels", help="Base channels directory (default: ./channels)")
    parser.add_argument("--model", default=cfg.get("model_size", "medium"), help="Whisper model size (default: medium)")
    parser.add_argument("--language", default=cfg.get("language", None), help="Language code e.g. 'en' (default: auto-detect)")
    parser.add_argument("--device", default=cfg.get("device", "cuda" if torch.cuda.is_available() else "cpu"))
    parser.add_argument("--timestamps", action=argparse.BooleanOptionalAction, default=cfg.get("return_timestamps", True))
    args = parser.parse_args()

    audio_dir = Path(args.base_dir) / args.channel / "audios"
    output_dir = Path(args.base_dir) / args.channel / "transcripts"

    if not audio_dir.exists():
        print(f"❌ Audio directory not found: {audio_dir}")
        raise SystemExit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    mp3_files = sorted(audio_dir.glob("*.mp3"))
    if not mp3_files:
        print(f"❌ No MP3 files found in {audio_dir}")
        raise SystemExit(1)

    print(f"🔊 Loading whisper-{args.model} on {args.device}...")
    model = whisper.load_model(args.model, device=args.device)
    print(f"✅ Model loaded. Transcribing {len(mp3_files)} files...\n" + "─" * 50)

    passed, failed = 0, []

    for i, audio_path in enumerate(mp3_files, 1):
        out_path = output_dir / (audio_path.stem + ".txt")

        if out_path.exists():
            print(f"[{i}/{len(mp3_files)}] ⏭️  Skipping {audio_path.name} (already done)\n")
            continue

        print(f"[{i}/{len(mp3_files)}] 🎙️  {audio_path.name}")
        try:
            result = model.transcribe(
                str(audio_path),
                language=args.language,
                fp16=(args.device == "cuda"),
                verbose=False,
            )

            with open(out_path, "w", encoding="utf-8") as f:
                if args.timestamps:
                    for seg in result["segments"]:
                        f.write(f"[{seg['start']:.1f}s -> {seg['end']:.1f}s] {seg['text'].strip()}\n")
                else:
                    f.write(result["text"])

            print(f"  ✅ Saved → {out_path}\n")
            passed += 1
        except Exception as e:
            print(f"  ❌ Failed: {e}\n")
            failed.append(audio_path.name)

    print("─" * 50)
    print(f"✅ Transcribed: {passed}  |  ❌ Failed: {len(failed)}")
    for name in failed:
        print(f"   - {name}")


if __name__ == "__main__":
    main()
