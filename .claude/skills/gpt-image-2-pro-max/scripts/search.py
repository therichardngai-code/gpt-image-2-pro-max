"""Search the gpt-image-2 prompt corpus.

Plain-text query, BM25-ranked, with a small tag-aware boost. Drives the
media-designer agent (see ~/.claude/agents/media-designer.md).

Examples:
  python scripts/search.py "luxury shoe ecommerce ad cream pastel"
  python scripts/search.py "moody cinematic portrait 35mm" --shape portrait -n 3
  python scripts/search.py "neon ui" --persist plans/neon-refs.md
  python scripts/search.py --list facets
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROMPTS_API = os.environ.get(
    "PROMPTS_API", "https://gpt-image-2-prompts.goclawoffice.com"
)

# Windows consoles default to cp1252; corpus contains CJK + emoji.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

FACETS = ["subjects", "styles", "lighting", "cameras",
          "moods", "palettes", "compositions", "mediums", "techniques", "usecases"]

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "")]


# ---------- Commands ----------

def list_command(what: str) -> None:
    """List facet names, or vocab items for a specific facet via /vocab/<facet>."""
    if what == "facets":
        for f in FACETS:
            print(f)
        return
    if what not in FACETS:
        raise SystemExit(
            f"unknown facet: {what}. Valid: {', '.join(FACETS)} (or 'facets')."
        )
    url = f"{PROMPTS_API}/vocab/{what}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "gpt-image-2-pro-max-cli/1.0",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"vocab request failed ({e.code}): {e.reason}")
    except Exception as e:
        raise SystemExit(f"vocab endpoint unreachable: {PROMPTS_API}\n  reason: {e}")
    for item in data.get("items", []):
        slug = item.get("slug", "")
        name = item.get("name", "")
        desc = item.get("description") or ""
        line = f"{slug:<24} {name}"
        if desc:
            line += f" — {desc}"
        print(line)


def _format_remote_tags(tags_dict: dict) -> str:
    parts = [f"{f}={','.join(s)}" for f, s in (tags_dict or {}).items() if s]
    return " | ".join(parts) if parts else "(no tags)"


def _render_remote_result(rank: int, r: dict, full: bool) -> str:
    """Render one server-returned record. `full=True` shows complete prompt body;
    `False` truncates to 400 chars with ellipsis."""
    img = (r.get("images") or [{}])[0]
    head = (
        f"#{rank}  bm25={r.get('bm25', 0):.2f}  shape={r.get('shape')}\n"
        f"  id    : {r.get('id')}\n"
        f"  title : {r.get('title')}\n"
        f"  author: @{r.get('author')}\n"
        f"  tweet : {r.get('twitter_link') or '(none)'}\n"
        f"  image : {img.get('url') or '(none)'}\n"
        f"  imgid : {img.get('image_id') or '(none)'}\n"
        f"  tags  : {_format_remote_tags(r.get('tags') or {})}\n"
    )
    pt = r.get("prompt_text") or "(no prompt body)"
    if not full and len(pt) > 400:
        pt = pt[:400] + "..."
    return head + "  prompt:\n" + "\n".join("    " + line for line in pt.splitlines()) + "\n"


def search_command(args: argparse.Namespace) -> None:
    """Run the search against the hosted endpoint and print results.

    Top-1 is always rendered with the FULL prompt body (the agent almost
    always wants the complete text of the best match for refactoring).
    Subsequent ranks truncate unless --full is set globally.
    """
    # Client-side guard: server rejects <3 unique tokens. Surface a clear
    # message before the round-trip so users know to broaden the brief.
    unique_tokens = {t for t in tokenize(args.query or "") if len(t) >= 2}
    if len(unique_tokens) < 3:
        print(
            "query too short — provide at least 3 descriptive words "
            "(e.g. 'anime portrait cinematic'). got: "
            f"{sorted(unique_tokens) or '(none)'}",
            file=sys.stderr,
        )
        return

    qs = {"q": args.query or "", "n": str(args.limit)}
    if args.shape:     qs["shape"] = args.shape
    if args.has_image: qs["has_image"] = "1"
    url = f"{PROMPTS_API}/search?{urllib.parse.urlencode(qs)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "gpt-image-2-pro-max-cli/1.0",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8")).get("error", str(e))
        except Exception:
            err = str(e)
        print(f"remote search rejected ({e.code}): {err}", file=sys.stderr)
        return
    except Exception as e:
        raise SystemExit(
            f"remote endpoint unreachable: {PROMPTS_API}\n"
            f"  reason: {e}\n"
            "Check your internet connection or set $PROMPTS_API to a different endpoint."
        )

    rows = data.get("results", [])
    if not rows:
        print("no records match")
        return

    # Top-1 always full (agent's typical use is to refactor the best match).
    # If user explicitly passed --full, all ranks are full.
    for i, r in enumerate(rows, 1):
        full_body = args.full or i == 1
        print(_render_remote_result(i, r, full_body))
    print(f"({data.get('count', len(rows))} matched, showing {len(rows)}; "
          f"top-1 shown in full)")

    if args.persist:
        _persist_remote(rows, args.query, args.persist)


def _persist_remote(rows: list[dict], query: str, persist_path: str) -> None:
    """Write top results to a markdown file with embedded reference images."""
    path = Path(persist_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sections = []
    for i, r in enumerate(rows, 1):
        img = (r.get("images") or [{}])[0]
        lines = [
            f"## {i}. {r.get('title')}",
            "",
            f"- id: `{r.get('id')}`",
            f"- author: @{r.get('author')}",
            f"- tweet: {r.get('twitter_link') or '(none)'}",
            f"- tags: {_format_remote_tags(r.get('tags') or {})}",
        ]
        if img.get("url"):
            lines.append(f"- image: {img['url']}")
            lines.append(f"\n![{r.get('id')}]({img['url']})")
        lines += ["", "```", r.get("prompt_text") or "(no prompt body)", "```", ""]
        sections.append("\n".join(lines))
    body = (
        f"# Prompt selection\n\nquery: `{query or '(none)'}`\n"
        f"endpoint: `{PROMPTS_API}`\n\n"
        + "\n---\n\n".join(sections)
    )
    path.write_text(body, encoding="utf-8")
    print(f"\nwrote {path.resolve()}")


# ---------- CLI ----------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("query", nargs="?", default="", help="free-text query")
    ap.add_argument("--shape",
                    help="portrait | poster | ui | character | comparison | "
                         "ecommerce | ad | thumbnail | infographic | comic")
    ap.add_argument("--has-image", action="store_true",
                    help="only records with at least one image url")
    ap.add_argument("-n", "--limit", type=int, default=5)
    ap.add_argument("--full", action="store_true",
                    help="show full prompt body for ALL ranks "
                         "(top-1 is always shown in full regardless)")
    ap.add_argument("--persist", metavar="PATH",
                    help="write top results to a markdown file with embedded images")
    ap.add_argument("--list", dest="list_target",
                    help="list facet names (`--list facets`) or vocab items "
                         "for a facet (`--list moods`, `--list palettes`, etc.)")
    args = ap.parse_args()

    if args.list_target:
        list_command(args.list_target)
    else:
        search_command(args)


if __name__ == "__main__":
    main()
