#!/usr/bin/env python3
"""ChatGPT (Codex) OAuth login — port of goclaw oauth/openai.go StartLoginOpenAI.

If the user is already signed in via the Codex CLI (~/.codex/auth.json),
this script just confirms and exits — no browser needed. Pass --force
to ignore an existing login and re-run the OAuth flow anyway.

Otherwise: PKCE flow against https://auth.openai.com/oauth/authorize.
Spawns a local HTTP server on 127.0.0.1:1455 to receive the callback,
opens the user's browser, exchanges the auth code for tokens, and persists
them via lib.chatgpt_oauth_token.save_session — which writes to
~/.codex/auth.json so the Codex CLI sees the same login.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html as html_lib
import http.server
import os
import secrets as pysecrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.chatgpt_oauth_token import (
    DEFAULT_API_BASE,
    OAuthSession,
    OPENAI_AUTH_URL,
    OPENAI_CLIENT_ID,
    OPENAI_REDIRECT_URI,
    OPENAI_SCOPES,
    OPENAI_TOKEN_URL,
    codex_auth_path,
    load_session,
    save_session,
    token_file_path,
)

CALLBACK_PORT = 1455


def _generate_pkce() -> tuple[str, str]:
    """Return (verifier, S256-challenge) — matches goclaw generatePKCE."""
    raw = pysecrets.token_bytes(64)
    verifier = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _build_auth_url(challenge: str, state: str) -> str:
    params = {
        "client_id": OPENAI_CLIENT_ID,
        "redirect_uri": OPENAI_REDIRECT_URI,
        "response_type": "code",
        "scope": OPENAI_SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        # Empirical params goclaw sends — kept verbatim for compat.
        "codex_cli_simplified_flow": "true",
        "id_token_add_organizations": "true",
        "originator": "pi",
    }
    return OPENAI_AUTH_URL + "?" + urllib.parse.urlencode(params)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    server_state: str = ""
    code_holder: list = []
    error_holder: list = []

    def log_message(self, fmt, *a):
        return  # silence stdout

    def do_GET(self):                                              # noqa: N802
        url = urllib.parse.urlparse(self.path)
        if url.path != "/auth/callback":
            self.send_response(404)
            self.end_headers()
            return
        q = urllib.parse.parse_qs(url.query)
        state = (q.get("state") or [""])[0]
        if state != self.server_state:
            body = b"<html><body><h2>Authentication Failed</h2><p>Invalid state.</p></body></html>"
            self._respond(400, body)
            self.error_holder.append("state mismatch (possible CSRF)")
            return
        code = (q.get("code") or [""])[0]
        if not code:
            err = (q.get("error") or ["no authorization code received"])[0]
            body = (
                f"<html><body><h2>Authentication Failed</h2>"
                f"<p>{html_lib.escape(err)}</p></body></html>"
            ).encode("utf-8")
            self._respond(400, body)
            self.error_holder.append(err)
            return
        body = b"<html><body><h2>Authentication Successful!</h2><p>You can close this window.</p></body></html>"
        self._respond(200, body)
        self.code_holder.append(code)

    def _respond(self, status: int, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _wait_for_callback(state: str, timeout_seconds: int) -> str:
    handler = _CallbackHandler
    handler.server_state = state
    handler.code_holder = []
    handler.error_holder = []
    httpd = http.server.HTTPServer(("127.0.0.1", CALLBACK_PORT), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    deadline = time.time() + timeout_seconds
    try:
        while time.time() < deadline:
            if handler.code_holder:
                return handler.code_holder[0]
            if handler.error_holder:
                raise RuntimeError(f"oauth callback: {handler.error_holder[0]}")
            time.sleep(0.25)
        raise TimeoutError("oauth callback timed out")
    finally:
        httpd.shutdown()
        httpd.server_close()


def _exchange_code(code: str, verifier: str) -> dict:
    resp = requests.post(
        OPENAI_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": OPENAI_CLIENT_ID,
            "code": code,
            "redirect_uri": OPENAI_REDIRECT_URI,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"token exchange failed (HTTP {resp.status_code}): {resp.text[:300]}"
        )
    return resp.json()


def main() -> int:
    p = argparse.ArgumentParser(
        description="ChatGPT (Codex) OAuth login for media-tools skill."
    )
    p.add_argument("--no-browser", action="store_true",
                   help="Print the auth URL but don't try to open a browser")
    p.add_argument("--timeout", type=int, default=300,
                   help="Seconds to wait for browser callback (default 300)")
    p.add_argument("--force", action="store_true",
                   help="Re-run OAuth even if a Codex login already exists")
    args = p.parse_args()

    if not args.force:
        existing = load_session()
        if existing and existing.access_token:
            src = codex_auth_path() if codex_auth_path().exists() else token_file_path()
            print("ChatGPT OAuth: already logged in.")
            print(f"  source: {src}")
            if existing.account_id:
                print(f"  account_id: {existing.account_id}")
            if existing.plan_type:
                print(f"  plan: {existing.plan_type}")
            print("Use --force to re-run the OAuth flow.")
            return 0

    verifier, challenge = _generate_pkce()
    state = base64.urlsafe_b64encode(pysecrets.token_bytes(16)).rstrip(b"=").decode("ascii")
    auth_url = _build_auth_url(challenge, state)

    print("ChatGPT OAuth login")
    print("If the browser doesn't open, visit:")
    print(f"  {auth_url}")
    print()

    if not args.no_browser:
        try:
            webbrowser.open(auth_url)
        except Exception:
            pass

    print(f"Waiting for callback on http://127.0.0.1:{CALLBACK_PORT}/auth/callback ...")
    try:
        code = _wait_for_callback(state, args.timeout)
    except (TimeoutError, RuntimeError) as e:
        print(f"login failed: {e}", file=sys.stderr)
        return 2

    try:
        token = _exchange_code(code, verifier)
    except Exception as e:                                        # noqa: BLE001
        print(f"token exchange failed: {e}", file=sys.stderr)
        return 3

    session = OAuthSession(
        access_token=token.get("access_token", ""),
        refresh_token=token.get("refresh_token", ""),
        expires_at=time.time() + int(token.get("expires_in", 0)),
        api_base=DEFAULT_API_BASE,
        scope=token.get("scope", ""),
    )
    if not session.access_token:
        print("login failed: missing access_token in response", file=sys.stderr)
        return 3
    save_session(session)

    print("Login successful.")
    print(f"Tokens saved to: {codex_auth_path()} (shared with Codex CLI)")
    print(f"               + {token_file_path()} (media-tools cache)")
    print(f"Access token expires in ~{int(token.get('expires_in', 0)) // 60} minutes "
          f"(auto-refreshed via refresh_token).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
