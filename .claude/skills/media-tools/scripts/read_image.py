#!/usr/bin/env python3
"""read_image CLI — full goclaw port with 4-provider vision chain.

Patterns ported from goclaw read_image.go:
- Provider chain: openrouter → gemini → anthropic → dashscope
  (skip if no API key, first success wins, cascade on failure)
- File path with MIME inference (jpg/png/gif/webp/bmp)
- 10MB max file size
- Default max_tokens=1024, temperature=0.3 (matches goclaw)
"""

import argparse
import base64
import sys
from pathlib import Path

# Force UTF-8 stdout/stderr — Windows defaults to cp1252 which crashes on
# any non-ASCII char in prompts (Vietnamese diacritics, Chinese, emojis).
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))

# .env auto-loads on first import of lib.env_keys (called from lib.chain).
from lib.chain import ChainError, execute_chain, resolve_chain
from lib.env_keys import VISION_PROVIDER_PRIORITY, has_credentials
from lib.providers import (
    anthropic_vision,
    dashscope_vision,
    gemini_vision,
    openrouter_vision,
)

VISION_REGISTRY = {
    "openrouter": openrouter_vision.analyze,
    "gemini":     gemini_vision.analyze,
    "anthropic":  anthropic_vision.analyze,
    "dashscope":  dashscope_vision.analyze,
}

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # matches goclaw maxImageFileBytes

MIME_TYPES = {
    ".jpg":  "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png":  "image/png",
    ".gif":  "image/gif",
    ".webp": "image/webp",
    ".bmp":  "image/bmp",
}


def load_image(path: str) -> dict:
    """Read file → {mime_type, data_b64}. Enforces extension + size cap."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"image file not found: {path}")
    ext = p.suffix.lower()
    mime = MIME_TYPES.get(ext)
    if not mime:
        raise ValueError(
            f"unsupported image format: {ext} "
            f"(supported: {', '.join(sorted(MIME_TYPES))})"
        )
    size = p.stat().st_size
    if size > MAX_IMAGE_BYTES:
        raise ValueError(
            f"image file too large ({size} bytes, max {MAX_IMAGE_BYTES})"
        )
    raw = p.read_bytes()
    return {"mime_type": mime, "data_b64": base64.b64encode(raw).decode("ascii")}


def _print_providers() -> int:
    """Diagnostic: show which vision providers are configured right now."""
    print("Vision provider chain (in priority order):")
    for name in VISION_PROVIDER_PRIORITY:
        ok = has_credentials(name)
        marker = "✓" if ok else "✗"
        print(f"  {marker} {name:<14}  ({name.upper()}_API_KEY env var)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Analyze an image via goclaw-style vision chain."
    )
    p.add_argument("--prompt", default="",
                   help="What to ask about the image (or use --prompt-file)")
    p.add_argument("--prompt-file", default="",
                   help="Read prompt from file (UTF-8). Use '-' for stdin.")
    p.add_argument("--path", default="",
                   help="Local image file (jpg/png/gif/webp/bmp, ≤10MB)")
    p.add_argument("--provider", default="",
                   help="Force a specific provider; bypasses chain")
    p.add_argument("--provider-order", default="",
                   help="Comma-separated chain override "
                        "(default: openrouter,gemini,anthropic,dashscope). "
                        "Can also be set via $MEDIA_TOOLS_VISION_ORDER or $MEDIA_TOOLS_PROVIDER_ORDER.")
    p.add_argument("--model", default="",
                   help="Override model for the selected provider")
    p.add_argument("--max-tokens", type=int, default=1024)
    p.add_argument("--temperature", type=float, default=0.3)
    p.add_argument("--list-providers", action="store_true",
                   help="Print which providers are configured right now and exit")
    args = p.parse_args()

    if args.list_providers:
        return _print_providers()

    if args.prompt_file:
        if args.prompt_file == "-":
            args.prompt = sys.stdin.read()
        else:
            try:
                args.prompt = Path(args.prompt_file).read_text(encoding="utf-8")
            except OSError as e:
                print(f"read_image: cannot read prompt file: {e}", file=sys.stderr)
                return 2

    if not args.prompt.strip():
        print("read_image: prompt is required (use --prompt or --prompt-file)",
              file=sys.stderr)
        return 2
    if not args.path:
        print("read_image: --path is required", file=sys.stderr)
        return 2

    try:
        image = load_image(args.path)
    except (FileNotFoundError, ValueError) as e:
        print(f"read_image: {e}", file=sys.stderr)
        return 2

    requested_order = None
    if args.provider_order:
        requested_order = [
            x.strip() for x in args.provider_order.split(",") if x.strip()
        ]
    chain = resolve_chain(
        kind="vision",
        requested_order=requested_order,
        forced_provider=args.provider or None,
    )

    params = {
        "prompt": args.prompt,
        "images": [image],
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
    }
    try:
        result = execute_chain(
            kind="vision",
            chain=chain,
            registry=VISION_REGISTRY,
            params=params,
            model_override=args.model,
        )
    except ChainError as e:
        print(f"read_image: {e}", file=sys.stderr)
        return 3
    except Exception as e:                                        # noqa: BLE001
        print(f"read_image: unexpected error: {e}", file=sys.stderr)
        return 4

    sys.stdout.write(
        f"Provider: {result.provider}\n"
        f"Model: {result.model}\n"
        f"---\n"
        f"{result.data.decode('utf-8', errors='replace')}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
