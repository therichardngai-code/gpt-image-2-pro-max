"""ChatGPT OAuth token storage + refresh — port of goclaw oauth/token.go.

Goclaw stores tokens in PostgreSQL (llm_providers.api_key + config_secrets.refresh_token).
We have no DB, so tokens persist as a JSON file. Same refresh semantics:
5-minute pre-expiry margin, refresh against https://auth.openai.com/oauth/token,
keep using the old token if refresh fails (might still work).

Storage strategy (in priority order):
  1. Codex CLI auth file at ~/.codex/auth.json — shared with the official
     Codex CLI so a single ChatGPT-Plus login works for both. Read AND
     written here when present so refreshes propagate to Codex too.
  2. Media-tools own JSON cache (legacy / fallback when Codex isn't installed):
       Windows : %APPDATA%\\media-tools\\chatgpt_oauth.json
       POSIX   : $XDG_CONFIG_HOME/media-tools/chatgpt_oauth.json
                 (default ~/.config/media-tools/chatgpt_oauth.json)

File mode 0600 on POSIX (best-effort on Windows).
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

# Constants ported verbatim from goclaw/internal/oauth/openai.go.
OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_AUTH_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_SCOPES = (
    "openid profile email offline_access "
    "api.connectors.read api.connectors.invoke"
)
OPENAI_REDIRECT_URI = "http://localhost:1455/auth/callback"
DEFAULT_API_BASE = "https://chatgpt.com/backend-api"
REFRESH_MARGIN_SECONDS = 5 * 60


@dataclass
class OAuthSession:
    access_token: str
    refresh_token: str
    expires_at: float          # unix seconds
    api_base: str = DEFAULT_API_BASE
    account_id: str = ""
    plan_type: str = ""
    scope: str = ""


def _config_dir() -> Path:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "media-tools"


def token_file_path() -> Path:
    """Return the absolute path of the media-tools OAuth token JSON file."""
    return _config_dir() / "chatgpt_oauth.json"


def codex_auth_path() -> Path:
    """Return the absolute path of the Codex CLI auth.json (~/.codex/auth.json)."""
    return Path.home() / ".codex" / "auth.json"


def _decode_jwt_exp(token: str) -> float:
    """Best-effort decode of a JWT's `exp` claim. Returns 0.0 on failure.

    No signature validation — we only need the expiry to schedule refresh.
    """
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return 0.0
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return float(data.get("exp", 0))
    except Exception:
        return 0.0


def _decode_id_token_chatgpt(token: str) -> tuple[str, str]:
    """Pull (account_id, plan_type) from Codex id_token's openai auth claim."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return "", ""
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        oai = data.get("https://api.openai.com/auth", {}) or {}
        return (
            str(oai.get("chatgpt_account_id", "") or ""),
            str(oai.get("chatgpt_plan_type", "") or ""),
        )
    except Exception:
        return "", ""


def _load_from_codex() -> OAuthSession | None:
    """Load an OAuthSession from the Codex CLI auth.json, if present.

    Codex format:
      { "OPENAI_API_KEY": ..., "tokens": { id_token, access_token,
        refresh_token, account_id }, "last_refresh": "..." }
    """
    p = codex_auth_path()
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return None
    tokens = raw.get("tokens") or {}
    access = tokens.get("access_token") or ""
    refresh = tokens.get("refresh_token") or ""
    if not access:
        return None
    account_id = tokens.get("account_id") or ""
    plan_type = ""
    id_tok = tokens.get("id_token") or ""
    if id_tok:
        a, pt = _decode_id_token_chatgpt(id_tok)
        account_id = account_id or a
        plan_type = pt
    return OAuthSession(
        access_token=access,
        refresh_token=refresh,
        expires_at=_decode_jwt_exp(access),
        api_base=DEFAULT_API_BASE,
        account_id=account_id,
        plan_type=plan_type,
        scope="",
    )


def _save_to_codex(s: OAuthSession) -> bool:
    """Write tokens back to ~/.codex/auth.json, preserving Codex's format.

    Returns True on success. Only updates `tokens.access_token`,
    `tokens.refresh_token`, `tokens.account_id`, and `last_refresh` —
    leaves `id_token` and `OPENAI_API_KEY` untouched if present.
    """
    p = codex_auth_path()
    try:
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            raw = {"OPENAI_API_KEY": None, "tokens": {}}
    except (OSError, ValueError):
        return False

    tokens = raw.setdefault("tokens", {})
    if s.access_token:
        tokens["access_token"] = s.access_token
    if s.refresh_token:
        tokens["refresh_token"] = s.refresh_token
    if s.account_id:
        tokens["account_id"] = s.account_id
    raw["last_refresh"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )
    try:
        with p.open("w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False


def _load_from_media_tools() -> OAuthSession | None:
    """Read tokens from the media-tools fallback file."""
    p = token_file_path()
    if not p.exists():
        return None
    try:
        with p.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        return OAuthSession(
            access_token=raw.get("access_token", ""),
            refresh_token=raw.get("refresh_token", ""),
            expires_at=float(raw.get("expires_at", 0)),
            api_base=raw.get("api_base", DEFAULT_API_BASE),
            account_id=raw.get("account_id", ""),
            plan_type=raw.get("plan_type", ""),
            scope=raw.get("scope", ""),
        )
    except (OSError, ValueError, TypeError):
        return None


def load_session() -> OAuthSession | None:
    """Read tokens. Codex auth.json wins; falls back to media-tools file."""
    return _load_from_codex() or _load_from_media_tools()


def save_session(s: OAuthSession) -> None:
    """Persist tokens. Always writes to Codex auth.json so the official Codex
    CLI shares the same login; also writes the media-tools fallback file as
    a cache (with our derived fields like expires_at/scope/plan_type).
    """
    _save_to_codex(s)
    p = token_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(asdict(s), f, indent=2)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


def has_valid_session() -> bool:
    """True if a session exists with a non-empty access token."""
    s = load_session()
    return s is not None and bool(s.access_token)


def refresh_token(refresh: str) -> dict:
    """Call OpenAI's refresh endpoint. Returns the raw token dict."""
    resp = requests.post(
        OPENAI_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": OPENAI_CLIENT_ID,
            "refresh_token": refresh,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"token refresh failed (HTTP {resp.status_code}): {resp.text[:300]}"
        )
    return resp.json()


def get_access_token() -> str:
    """Return a valid access token; refresh if within REFRESH_MARGIN of expiry.

    Mirrors goclaw DBTokenSource.Token() behavior — including the fallback
    where, if refresh fails but we still hold a token, return it anyway
    (might still work).
    """
    s = load_session()
    if s is None:
        raise RuntimeError(
            "No ChatGPT OAuth session found. Looked in:\n"
            f"  - {codex_auth_path()} (Codex CLI)\n"
            f"  - {token_file_path()} (media-tools cache)\n"
            "Fix: run `python scripts/chatgpt_oauth_login.py` to authenticate, "
            "or install + login to the Codex CLI."
        )
    now = time.time()
    if s.access_token and (s.expires_at - now) > REFRESH_MARGIN_SECONDS:
        return s.access_token

    if not s.refresh_token:
        if s.access_token:
            return s.access_token
        raise RuntimeError(
            "OAuth session has access_token but no refresh_token. "
            "Re-login: `python scripts/chatgpt_oauth_login.py --force`"
        )

    try:
        token_data = refresh_token(s.refresh_token)
    except Exception as e:                                        # noqa: BLE001
        if s.access_token:
            print(
                f"chatgpt_oauth: token refresh failed, using existing token: {e}",
                file=sys.stderr,
            )
            return s.access_token
        raise

    s.access_token = token_data.get("access_token", "")
    if rt := token_data.get("refresh_token"):
        s.refresh_token = rt
    s.expires_at = now + int(token_data.get("expires_in", 0))
    if scope := token_data.get("scope"):
        s.scope = scope
    save_session(s)
    if not s.access_token:
        raise RuntimeError("refresh response missing access_token")
    return s.access_token
