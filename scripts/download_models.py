#!/usr/bin/env python3
"""
Model Provisioning & Weight Download Script
============================================
Automates pulling Ollama model weights (~17GB) and downloading the Kokoro-82M
ONNX speech model (~2.5GB) plus its voice mapping JSON.

Usage:
  python scripts/download_models.py [--skip-ollama] [--skip-kokoro] [--ollama-only MODEL]
  python scripts/download_models.py --dry-run   # Print what would be downloaded

Expected runtime: 30 min – 4 hours depending on bandwidth.
"""

import os
import sys
import subprocess
import argparse
import json
from pathlib import Path
from urllib.request import urlretrieve
from urllib.error import URLError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "backend" / "app" / "models"

OLLAMA_MODELS = {
    "qwen2.5:latest":  {"size_gb": 4.7, "description": "Fast Mediator (System 1) — 8B instruct"},
    "qwen2.5:14b":     {"size_gb": 9.0, "description": "Slow Critique (System 2) — 14B instruct"},
    "llava:latest":     {"size_gb": 4.7, "description": "Vision OCR Engine — 7B multimodal"},
    "nomic-embed-text": {"size_gb": 0.27, "description": "Semantic Search Embeddings"},
}

KOKORO_FILES = {
    "kokoro-v0.19.onnx": {
        "url": "https://github.com/theonlygust/kokoro-onnx/releases/download/v0.2.0/kokoro-v0.19.onnx",
        "size_gb": 2.5,
    },
    "voices.json": {
        "url": "https://github.com/theonlygust/kokoro-onnx/releases/download/v0.2.0/voices.json",
        "size_gb": 0.002,
    },
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def run(cmd: list[str]) -> bool:
    """Run a shell command, streaming stdout. Returns True on success."""
    print(f"  ⏳ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode == 0


def download_file(url: str, dest: Path) -> bool:
    """Download a file with a progress hook. Returns True on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  ⏬ {url}  →  {dest}")

    def _progress(block_num, block_size, total_size):
        if total_size > 0:
            done = block_num * block_size
            pct = min(100, int(done / total_size * 100))
            print(f"     {pct}% ({done // 1024 // 1024} / {total_size // 1024 // 1024} MB)", end="\r")

    try:
        urlretrieve(url, dest, reporthook=_progress)
        print()  # newline after progress
        return dest.exists() and dest.stat().st_size > 0
    except URLError as exc:
        print(f"\n  ❌ Download failed: {exc}")
        return False


# ── Sub-commands ─────────────────────────────────────────────────────────────

def download_ollama(dry_run: bool = False, model_filter: str | None = None):
    """Pull Ollama model weights sequentially to avoid link saturation."""
    models_to_pull = OLLAMA_MODELS
    if model_filter:
        models_to_pull = {k: v for k, v in OLLAMA_MODELS.items() if k == model_filter}
        if not models_to_pull:
            print(f"Unknown model: {model_filter}")
            print(f"Available: {', '.join(OLLAMA_MODELS)}")
            sys.exit(1)

    total_gb = sum(v["size_gb"] for v in models_to_pull.values())
    print(f"\n📦 Ollama Models ({len(models_to_pull)} total, ~{total_gb:.1f} GB)")
    print("-" * 50)

    if dry_run:
        for name, info in models_to_pull.items():
            print(f"  [DRY-RUN] Would pull: {name} ({info['size_gb']} GB) — {info['description']}")
        return

    for name, info in models_to_pull.items():
        print(f"\n  📥 Pulling {name} ({info['size_gb']} GB) — {info['description']}")
        if not run(["ollama", "pull", name]):
            print(f"  ⚠️  Failed to pull {name} — continuing with remaining models")
            continue
        print(f"  ✅ {name} pulled successfully")

    # Verify
    print("\n  🔍 Verifying installed models...")
    run(["ollama", "list"])


def download_kokoro(dry_run: bool = False):
    """Download Kokoro-82M ONNX model and voice JSON."""
    total_gb = sum(v["size_gb"] for v in KOKORO_FILES.values())
    print(f"\n🎙️  Kokoro-82M TTS Engine ({len(KOKORO_FILES)} files, ~{total_gb:.2f} GB)")
    print("-" * 50)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if dry_run:
        for filename, info in KOKORO_FILES.items():
            dest = MODELS_DIR / filename
            print(f"  [DRY-RUN] Would download: {info['url']}  →  {dest}")
        return

    for filename, info in KOKORO_FILES.items():
        dest = MODELS_DIR / filename
        print(f"\n  📥 {filename} ({info['size_gb']} GB)")
        if dest.exists():
            existing_size = dest.stat().st_size / (1024**3)
            print(f"     File exists ({existing_size:.2f} GB). Skipping. Delete to re-download.")
            continue
        if not download_file(info["url"], dest):
            print(f"  ⚠️  Failed to download {filename}")
            continue
        print(f"  ✅ {filename} saved ({dest.stat().st_size / 1024**2:.1f} MB)")

    print(f"\n  📁 Models directory: {MODELS_DIR}")
    for f in sorted(MODELS_DIR.glob("*")):
        print(f"     {f.name}  ({f.stat().st_size / 1024**2:.1f} MB)")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Download Ollama models and Kokoro-82M ONNX speech engine for The Estate Steward"
    )
    parser.add_argument("--dry-run", action="store_true", help="Print what would be downloaded without downloading")
    parser.add_argument("--skip-ollama", action="store_true", help="Skip Ollama model downloads")
    parser.add_argument("--skip-kokoro", action="store_true", help="Skip Kokoro ONNX downloads")
    parser.add_argument("--ollama-only", type=str, metavar="MODEL", help="Download only a specific Ollama model")
    args = parser.parse_args()

    print("═" * 60)
    print("  The Estate Steward — Model Provisioning Script")
    print("═" * 60)

    if args.dry_run:
        print("  🔍 DRY RUN — no files will be downloaded\n")

    if not args.skip_ollama:
        download_ollama(dry_run=args.dry_run, model_filter=args.ollama_only)

    if not args.skip_kokoro:
        download_kokoro(dry_run=args.dry_run)

    print("\n" + "═" * 60)
    if args.dry_run:
        print("  Dry run complete. Remove --dry-run to execute downloads.")
    else:
        print("  All model downloads complete.")
    print("═" * 60)


if __name__ == "__main__":
    main()