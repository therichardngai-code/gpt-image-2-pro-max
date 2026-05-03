r"""Tiny .env loader — no third-party deps.

Looks for a `.env` file in (priority order):
  1. $MEDIA_TOOLS_ENV (explicit override path)
  2. <skill_root>/.env  (i.e. .claude/skills/media-tools/.env)
  3. ~/.config/media-tools/.env (or %APPDATA%\media-tools\.env on Windows)

Existing os.environ values are NEVER overwritten — env wins over file.
Lines: `KEY=VALUE`, `#` comments, blank lines ignored.
Quotes (single/double) around VALUE are stripped. No interpolation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _skill_root() -> Path:
    # this file: .claude/skills/media-tools/scripts/lib/dotenv_loader.py
    return Path(__file__).resolve().parents[2]


def _user_config_env() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "media-tools" / ".env"


def candidate_paths() -> list[Path]:
    paths: list[Path] = []
    override = os.environ.get("MEDIA_TOOLS_ENV", "").strip()
    if override:
        paths.append(Path(override))
    paths.append(_skill_root() / ".env")
    paths.append(_user_config_env())
    return paths


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if (val.startswith('"') and val.endswith('"')) or \
           (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        if key:
            out[key] = val
    return out


def load() -> Path | None:
    """Load the first existing .env into os.environ. Returns the path used,
    or None if nothing was found. Existing env vars are preserved.
    """
    for p in candidate_paths():
        if p.exists():
            try:
                pairs = _parse(p.read_text(encoding="utf-8"))
            except OSError:
                continue
            for k, v in pairs.items():
                os.environ.setdefault(k, v)
            return p
    return None
