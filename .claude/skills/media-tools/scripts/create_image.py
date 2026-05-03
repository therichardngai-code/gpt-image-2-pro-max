#!/usr/bin/env python3
"""create_image CLI — full goclaw port with 7-provider chain.

Patterns ported from goclaw create_image.go + per-provider files:
- Provider chain: chatgpt_oauth → openrouter → gemini → openai → minimax → dashscope → byteplus
  (skip if no API key / OAuth session, first success wins, cascade on failure)
- Aspect ratio: 1:1 / 3:4 / 4:3 / 9:16 / 16:9 (each provider maps to its own size format)
- PNG tEXt prompt embedding so the file carries its provenance
- Date-based folder: <workspace>/generated/<YYYY-MM-DD>/<slug>-<ts>-<rand>.png
- Output: MEDIA:<path> + provider/model echo (matches goclaw Result.ForLLM)
"""

import argparse
import re
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
from lib.env_keys import IMAGE_PROVIDER_PRIORITY, has_credentials
from lib.filename import date_folder, media_filename
from lib.png_metadata import embed_prompt
from lib.providers import (
    byteplus_image,
    chatgpt_oauth_image,
    dashscope_image,
    gemini_image,
    minimax_image,
    openai_image,
    openrouter_image,
)

IMAGE_REGISTRY = {
    "chatgpt_oauth": chatgpt_oauth_image.generate,
    "openrouter":    openrouter_image.generate,
    "gemini":        gemini_image.generate,
    "openai":        openai_image.generate,
    "minimax":       minimax_image.generate,
    "dashscope":     dashscope_image.generate,
    "byteplus":      byteplus_image.generate,
}

VALID_RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9"}


def _slug_from_prompt(prompt: str, max_words: int = 5) -> str:
    """Derive a kebab-case filename hint from the first words of a prompt.

    Strips punctuation, keeps alphanumerics + hyphens. Falls back to
    'image' if nothing usable. Lowercased for filesystem-friendliness.
    """
    cleaned = re.sub(r"[^\w\s-]", " ", prompt.lower(), flags=re.UNICODE)
    words = [w for w in cleaned.split() if w][:max_words]
    slug = "-".join(words)
    return slug or "image"


def _print_providers() -> int:
    """Diagnostic: show which image providers are configured right now."""
    print("Image provider chain (in priority order):")
    for name in IMAGE_PROVIDER_PRIORITY:
        ok = has_credentials(name)
        marker = "✓" if ok else "✗"
        if name == "chatgpt_oauth":
            src = "Codex/media-tools OAuth session"
        else:
            src = f"{name.upper()}_API_KEY env var"
        print(f"  {marker} {name:<14}  ({src})")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Generate an image via goclaw-style provider chain."
    )
    p.add_argument("--prompt", default="",
                   help="Prompt text (or use --prompt-file for long prompts)")
    p.add_argument("--prompt-file", default="",
                   help="Read prompt from file (UTF-8). Use '-' for stdin. "
                        "Useful for long / multi-line / non-ASCII prompts on Windows.")
    p.add_argument("--aspect-ratio", default="1:1", choices=sorted(VALID_RATIOS))
    p.add_argument("--filename-hint", default="",
                   help="Kebab-slug for output file (no extension). "
                        "Auto-derived from first 5 words of prompt if omitted.")
    p.add_argument("--workspace", default="",
                   help="Output dir; defaults to $WEB_TOOLS_WORKSPACE or OS temp")
    p.add_argument("--provider", default="",
                   help="Force a specific provider; bypasses chain")
    p.add_argument("--provider-order", default="",
                   help="Comma-separated chain override "
                        "(default: chatgpt_oauth,openrouter,gemini,openai,minimax,dashscope,byteplus). "
                        "Can also be set via $MEDIA_TOOLS_IMAGE_ORDER or $MEDIA_TOOLS_PROVIDER_ORDER.")
    p.add_argument("--model", default="",
                   help="Override model for the selected provider "
                        "(chatgpt_oauth: outer Codex Responses model, default gpt-5.4)")
    p.add_argument("--image-model", default="",
                   help="chatgpt_oauth only — image_generation model. "
                        "Whitelist: gpt-image-2 (default), gpt-image-1.5 (legacy)")
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
                print(f"create_image: cannot read prompt file: {e}", file=sys.stderr)
                return 2

    if not args.prompt.strip():
        print("create_image: prompt is required (use --prompt or --prompt-file)",
              file=sys.stderr)
        return 2

    if not args.filename_hint:
        args.filename_hint = _slug_from_prompt(args.prompt)

    requested_order = None
    if args.provider_order:
        requested_order = [
            x.strip() for x in args.provider_order.split(",") if x.strip()
        ]
    chain = resolve_chain(
        kind="image",
        requested_order=requested_order,
        forced_provider=args.provider or None,
    )

    params = {
        "prompt": args.prompt,
        "aspect_ratio": args.aspect_ratio,
        "image_model": args.image_model,  # used by chatgpt_oauth provider
    }
    try:
        result = execute_chain(
            kind="image",
            chain=chain,
            registry=IMAGE_REGISTRY,
            params=params,
            model_override=args.model,
        )
    except ChainError as e:
        print(f"create_image: {e}", file=sys.stderr)
        return 3
    except Exception as e:                                        # noqa: BLE001
        print(f"create_image: unexpected error: {e}", file=sys.stderr)
        return 4

    image_data = embed_prompt(result.data, args.prompt)
    folder = date_folder(args.workspace)
    name = media_filename("image", args.filename_hint, "png")
    out_path = folder / name
    out_path.write_bytes(image_data)

    sys.stdout.write(
        f"MEDIA:{out_path}\n"
        f"Provider: {result.provider}\n"
        f"Model: {result.model}\n"
        f"Bytes: {len(image_data)}\n"
        f"Prompt: {args.prompt}\n"
        f"Use the EXACT filename when referencing: {name}\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
