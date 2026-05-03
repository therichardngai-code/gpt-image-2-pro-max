"""Filename + workspace path helpers — port of goclaw mediaFileName logic.

Output structure: <workspace>/generated/<YYYY-MM-DD>/<slug>-<timestamp>.<ext>
Hint is sanitized to a kebab-slug; timestamp prevents collisions when the
same hint is reused in the same day.
"""

import os
import re
import secrets
import tempfile
import time
from datetime import date
from pathlib import Path

_INVALID_FILENAME_RE = re.compile(r"[^a-z0-9-]+")
_DEDUPE_DASH_RE = re.compile(r"-{2,}")


def slugify(hint: str, fallback: str = "image") -> str:
    """Convert a free-form hint to a safe kebab-slug. Empty → fallback."""
    if not hint:
        return fallback
    s = hint.strip().lower().replace(" ", "-").replace("_", "-")
    s = _INVALID_FILENAME_RE.sub("", s)
    s = _DEDUPE_DASH_RE.sub("-", s).strip("-")
    return s or fallback


def media_filename(kind: str, hint: str, ext: str) -> str:
    """Build a unique filename: <slug>-<unix-ts>-<rand4>.<ext>"""
    slug = slugify(hint, fallback=kind)
    ts = int(time.time())
    rand = secrets.token_hex(2)
    return f"{slug}-{ts}-{rand}.{ext}"


def date_folder(workspace: str) -> Path:
    """Return <workspace>/generated/<YYYY-MM-DD>/, creating it if needed."""
    ws = workspace or os.environ.get("WEB_TOOLS_WORKSPACE", "")
    if not ws:
        ws = tempfile.gettempdir()
    folder = Path(ws) / "generated" / date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    return folder
