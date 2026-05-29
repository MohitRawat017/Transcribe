import argparse
import os
import yaml
import torch
from pathlib import Path
from faster_whisper import WhisperModel


def load_config(path: str = "config.yaml") -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return yaml.safe_load(f)
    return {}


def main():
    cfg = load_config()

    parser = argparse.ArgumentParser(description="Transcribe audio files using faster-whisper.")
    parser.add_argument("channel", help="Channel folder name under ./channels/")
    parser.add_argument("--base-dir", default="./channels")
    parser.add_argument("--model", default=cfg.get("model", "Systran/faster-distil-whisper-large-v3"))
    parser.add_argument("--language", default=cfg.get("language", "en"))
    parser.add_argument("--device", default=cfg.get("device", "cuda" if torch.cuda.is_available() else "cpu"))
    parser.add_argument("--compute-type", default=cfg.get("compute_type", "float16"))
    parser.add_argument("--timestamps", action=argparse.BooleanOptionalAction, default=cfg.get("return_timestamps", True))
    args = parser.parse_args()

    audio_dir  = Path(args.base_dir) / args.channel / "audios"
    output_dir = Path(args.base_dir) / args.channel / "transcripts"

    if not audio_dir.exists():
        print(f"Error: audio directory not found: {audio_dir}")
        raise SystemExit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    audio_files = sorted(
        p for p in audio_dir.iterdir()
        if p.suffix.lower() in {".mp3", ".opus", ".ogg", ".m4a", ".webm", ".wav"}
    )
    if not audio_files:
        print(f"Error: no audio files found in {audio_dir}")
        raise SystemExit(1)

    print(f"Loading {args.model} on {args.device} ({args.compute_type})...")
    model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    print(f"Model loaded. Transcribing {len(audio_files)} files...")
    print("-" * 60)

    passed, failed = 0, []

    for i, audio_path in enumerate(audio_files, 1):
        out_path = output_dir / (audio_path.stem + ".txt")

        if out_path.exists():
            print(f"[{i}/{len(audio_files)}] Skipping {audio_path.name} (already done)\n")
            continue

        print(f"[{i}/{len(audio_files)}] {audio_path.name}")
        try:
            segments, info = model.transcribe(
                str(audio_path),
                language=args.language,
                beam_size=5,
                vad_filter=True,
            )
            duration = info.duration

            with open(out_path, "w", encoding="utf-8") as f:
                for seg in segments:
                    pct = int(seg.end / duration * 30) if duration else 0
                    bar = "#" * pct + "-" * (30 - pct)
                    print(f"\r  [{bar}] {seg.end / duration * 100:5.1f}%", end="", flush=True)
                    if args.timestamps:
                        f.write(f"[{seg.start:.1f}s -> {seg.end:.1f}s] {seg.text.strip()}\n")
                    else:
                        f.write(seg.text.strip() + "\n")
            print()

            print(f"  Saved -> {out_path}\n")
            passed += 1
        except Exception as e:
            print(f"  Failed: {e}\n")
            failed.append(audio_path.name)

    print("-" * 60)
    print(f"Transcribed: {passed}  Failed: {len(failed)}")
    for name in failed:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
