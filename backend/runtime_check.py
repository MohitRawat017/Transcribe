import importlib
import json
import shutil
import sys


def runtime_report() -> dict:
    modules = ["fastapi", "uvicorn", "yt_dlp"]
    return {
        "python": sys.version.split()[0],
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "deno": bool(shutil.which("deno")),
        "modules": {name: importlib.import_module(name).__name__ for name in modules},
    }


def main() -> None:
    print(json.dumps(runtime_report(), sort_keys=True))


if __name__ == "__main__":
    main()
