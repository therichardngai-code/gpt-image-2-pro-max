"""Search the gpt-image-2 prompt corpus.

Plain-text query, BM25-ranked, with a small tag-aware boost. Drives the
media-designer agent (see agents/media-designer.md).

Examples:
  python scripts/search.py "luxury shoe ecommerce ad cream pastel" --has-prompt
  python scripts/search.py "moody cinematic portrait 35mm" --shape portrait -n 3
  python scripts/search.py --author Polanco_IA --has-prompt --full
  python scripts/search.py "neon ui" --persist plans/neon-refs.md
  python scripts/search.py --list moods
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

PROMPTS_API = os.environ.get(
    "PROMPTS_API", "https://gpt-image-2-prompts.goclawoffice.com"
)
USE_REMOTE = os.environ.get("PROMPTS_LOCAL") != "1"  # set PROMPTS_LOCAL=1 to force local

# Windows consoles default to cp1252; corpus contains CJK + emoji.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
VOCAB_DIR = DATA / "vocab"
PROMPTS_PATH = DATA / "prompts.json"

FACETS = ["subjects", "styles", "lighting", "cameras",
          "moods", "palettes", "compositions", "mediums", "techniques", "usecases"]

# ---------- BM25 ----------

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "")]


def doc_text(rec: dict) -> str:
    return " ".join([
        rec.get("title", ""),
        rec.get("prompt_text", ""),
        rec.get("non_prompt_text", ""),
        rec.get("category", ""),
        rec.get("shape", ""),
        rec.get("author", ""),
    ])


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.N = len(docs)
        self.avgdl = sum(len(d) for d in docs) / self.N if self.N else 0.0
        self.df: Counter[str] = Counter()
        for d in docs:
            for term in set(d):
                self.df[term] += 1
        self.idf = {
            t: math.log(1 + (self.N - df + 0.5) / (df + 0.5))
            for t, df in self.df.items()
        }
        self.docs = docs

    def score(self, query: list[str], idx: int) -> float:
        d = self.docs[idx]
        if not d:
            return 0.0
        tf = Counter(d)
        dl = len(d)
        s = 0.0
        for q in query:
            f = tf.get(q, 0)
            if not f:
                continue
            s += self.idf.get(q, 0.0) * (f * (self.k1 + 1)) / (
                f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            )
        return s


# ---------- I/O ----------

def load_records() -> list[dict]:
    raise SystemExit(
        f"remote endpoint unreachable: {PROMPTS_API}\n"
        "Check your internet connection or set PROMPTS_API to a different endpoint."
    )


def load_vocab(facet: str) -> list[dict]:
    path = VOCAB_DIR / f"{facet}.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------- Filter ----------

def filter_records(records: list[dict], shape: str | None, author: str | None,
                   has_prompt: bool, source: str | None = None,
                   has_image: bool = False) -> list[dict]:
    out = []
    for r in records:
        if shape and r.get("shape") != shape:
            continue
        if source and r.get("source") != source:
            continue
        if author and author.lower() not in r.get("author", "").lower():
            continue
        if has_prompt and not r.get("prompt_text"):
            continue
        if has_image and not r.get("media_urls"):
            continue
        out.append(r)
    return out


# ---------- Output ----------

def format_tags(rec: dict) -> str:
    tags = rec.get("tags") or {}
    parts = [f"{f}={','.join(tags[f])}" for f in FACETS if tags.get(f)]
    return " | ".join(parts) if parts else "(no tags)"


def _first(lst):
    return lst[0] if isinstance(lst, list) and lst else None


def render_result(rank: int, score: float, rec: dict, full: bool) -> str:
    image_url = _first(rec.get("media_urls"))
    image_id = _first(rec.get("media_image_ids"))
    image_local = _first(rec.get("media_unified_paths")) or _first(rec.get("media_local_paths"))
    n_images = len(rec.get("media_urls") or rec.get("media_image_ids") or [])
    head = (
        f"#{rank}  score={score:.2f}  shape={rec.get('shape')}  source={rec.get('source')}\n"
        f"  id    : {rec.get('id')}\n"
        f"  title : {rec.get('title')}\n"
        f"  author: @{rec.get('author')}\n"
        f"  tweet : {rec.get('tweet_url') or '(none)'}\n"
        f"  image : {image_url or '(no url)'}{f'  (+{n_images-1} more)' if n_images > 1 else ''}\n"
        f"  imgid : {image_id or '(none)'}\n"
        f"  local : {image_local or '(not downloaded)'}\n"
        f"  tags  : {format_tags(rec)}\n"
    )
    pt = rec.get("prompt_text") or "(no prompt text on record; see tweet_url)"
    if not full:
        pt = pt[:400] + ("..." if len(pt) > 400 else "")
    return head + "  prompt:\n" + "\n".join("    " + line for line in pt.splitlines()) + "\n"


# ---------- Commands ----------

def list_command(what: str) -> None:
    if what == "facets":
        for f in FACETS:
            print(f)
        return
    if what in FACETS:
        for r in load_vocab(what):
            print(f"{r['slug']:25s}  {r['name']:25s}  {r['description']}")
        return
    raise SystemExit(f"unknown list target '{what}'. try: facets | {' | '.join(FACETS)}")


def remote_search(args: argparse.Namespace) -> bool:
    """Hit the Worker; return True if handled, False to fall back to local."""
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
        return True  # handled (rejected); don't fall back

    qs = {"q": args.query or "", "n": str(args.limit)}
    if args.shape: qs["shape"] = args.shape
    if args.source: qs["source"] = args.source
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
        # Worker rejected the request (e.g. 400 short query, 403 origin block).
        # Surface its JSON error message instead of hiding behind local fallback.
        try:
            err = json.loads(e.read().decode("utf-8")).get("error", str(e))
        except Exception:
            err = str(e)
        print(f"remote search rejected ({e.code}): {err}", file=sys.stderr)
        return True  # handled; don't fall back
    except Exception as e:
        print(f"(remote search failed: {e}; falling back to local)", file=sys.stderr)
        return False

    rows = data.get("results", [])
    if not rows:
        print("no records match")
        return True

    for i, r in enumerate(rows, 1):
        img = (r.get("images") or [{}])[0]
        tag_str = " | ".join(f"{f}={','.join(s)}" for f, s in (r.get("tags") or {}).items() if s) or "(no tags)"
        head = (
            f"#{i}  bm25={r.get('bm25', 0):.2f}  shape={r.get('shape')}  source={r.get('source')}\n"
            f"  id    : {r.get('id')}\n"
            f"  title : {r.get('title')}\n"
            f"  author: @{r.get('author')}\n"
            f"  tweet : {r.get('twitter_link') or '(none)'}\n"
            f"  image : {img.get('url') or '(none)'}\n"
            f"  imgid : {img.get('image_id') or '(none)'}\n"
            f"  tags  : {tag_str}\n"
        )
        pt = r.get("prompt_text") or "(no prompt body)"
        if not args.full and len(pt) > 400:
            pt = pt[:400] + "..."
        print(head + "  prompt:\n" + "\n".join("    " + line for line in pt.splitlines()) + "\n")
    print(f"({data.get('count', len(rows))} matched, showing {len(rows)})")

    if args.persist:
        path = Path(args.persist)
        path.parent.mkdir(parents=True, exist_ok=True)
        sections = []
        for i, r in enumerate(rows, 1):
            img = (r.get("images") or [{}])[0]
            tag_str = " | ".join(f"{f}={','.join(s)}" for f, s in (r.get("tags") or {}).items() if s) or "(no tags)"
            lines = [
                f"## {i}. {r.get('title')}",
                "",
                f"- id: `{r.get('id')}` (source: {r.get('source')})",
                f"- author: @{r.get('author')}",
                f"- tweet: {r.get('twitter_link') or '(none)'}",
                f"- tags: {tag_str}",
            ]
            if img.get("url"):
                lines.append(f"- image: {img['url']}")
                lines.append(f"\n![{r.get('id')}]({img['url']})")
            lines += ["", "```", r.get("prompt_text") or "(no prompt body)", "```", ""]
            sections.append("\n".join(lines))
        body = (
            f"# Prompt selection\n\nquery: `{args.query or '(none)'}`\n"
            f"endpoint: `{PROMPTS_API}`\n\n"
            + "\n---\n\n".join(sections)
        )
        path.write_text(body, encoding="utf-8")
        print(f"\nwrote {path.resolve()}")
    return True


def search_command(args: argparse.Namespace) -> None:
    if USE_REMOTE and PROMPTS_API and remote_search(args):
        return
    records = load_records()
    pool = filter_records(records, args.shape, args.author, args.has_prompt,
                          source=args.source, has_image=args.has_image)
    if not pool:
        print("no records match filters")
        return

    # Score = BM25(query) + 0.5 per record-tag whose slug contains a query
    # token (so "luxury" boosts moods=luxurious, "shoe" boosts subjects=product).
    if args.query:
        docs = [tokenize(doc_text(r)) for r in pool]
        bm25 = BM25(docs)
        q = tokenize(args.query)
        long_tokens = {t for t in q if len(t) > 3}
        scored = []
        for i, r in enumerate(pool):
            base = bm25.score(q, i)
            tag_bonus = 0.0
            for slugs in (r.get("tags") or {}).values():
                for slug in slugs:
                    if any(tok in slug for tok in long_tokens):
                        tag_bonus += 0.5
            scored.append((base + tag_bonus, r))
        scored.sort(key=lambda x: x[0], reverse=True)
    else:
        # No query — browse mode, ranked by tag richness.
        def richness(r: dict) -> int:
            return sum(len(s) for s in (r.get("tags") or {}).values())
        scored = sorted(((richness(r), r) for r in pool),
                        key=lambda x: x[0], reverse=True)

    top = scored[: args.limit]
    print("\n".join(render_result(i + 1, s, r, args.full)
                    for i, (s, r) in enumerate(top)))
    print(f"({len(pool)} matched, showing {len(top)})")

    if args.persist:
        path = Path(args.persist)
        path.parent.mkdir(parents=True, exist_ok=True)
        def _section(i: int, r: dict) -> str:
            img = _first(r.get("media_urls"))
            local = _first(r.get("media_unified_paths")) or _first(r.get("media_local_paths"))
            lines = [
                f"## {i+1}. {r.get('title')}",
                "",
                f"- id: `{r.get('id')}` (source: {r.get('source')})",
                f"- author: @{r.get('author')}",
                f"- tweet: {r.get('tweet_url') or '(none)'}",
                f"- tags: {format_tags(r)}",
            ]
            if img:
                lines.append(f"- image: {img}")
            if local:
                lines.append(f"- local: `{local}`")
                lines.append(f"\n![{r.get('id')}]({local})")
            lines += ["", "```", r.get("prompt_text") or "(prompt not on record)", "```", ""]
            return "\n".join(lines)

        body = (
            f"# Prompt selection\n\nquery: `{args.query or '(none)'}`\n\n"
            + "\n---\n\n".join(_section(i, r) for i, (_, r) in enumerate(top))
        )
        path.write_text(body, encoding="utf-8")
        print(f"\nwrote {path}")


# ---------- CLI ----------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("query", nargs="?", default="", help="free-text query")
    ap.add_argument("--shape", help="portrait | poster | ui | character | comparison | ecommerce | ad | thumbnail | infographic | comic")
    ap.add_argument("--source", help=argparse.SUPPRESS)
    ap.add_argument("--author", help=argparse.SUPPRESS)
    ap.add_argument("--has-prompt", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--has-image", action="store_true",
                    help="only records with at least one image url")
    ap.add_argument("-n", "--limit", type=int, default=5)
    ap.add_argument("--full", action="store_true", help="don't truncate prompt body")
    ap.add_argument("--persist", metavar="PATH", help="write top results to a markdown file")
    ap.add_argument("--list", dest="list_target",
                    help="list one of: facets | <facet-name>")
    args = ap.parse_args()

    if args.list_target:
        list_command(args.list_target)
    else:
        search_command(args)


if __name__ == "__main__":
    main()
