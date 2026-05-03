"""Gemini native image generation — port of callGeminiNativeImageGen.

Uses Google's native generateContent API with responseModalities=[TEXT,IMAGE].
Gemini image models DON'T support OpenAI-compat endpoints; this is the
only path. Image arrives as inlineData in candidates[0].content.parts[].
"""

import base64
import json
from typing import Any

import requests

TIMEOUT_SECONDS = 120


def generate(api_key: str, api_base: str, model: str,
             params: dict[str, Any]) -> bytes:
    prompt = params.get("prompt", "")

    # Strip /openai compat suffix if env override provided one.
    native_base = api_base.rstrip("/")
    if native_base.endswith("/openai"):
        native_base = native_base[:-len("/openai")]

    url = f"{native_base}/models/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }

    resp = requests.post(
        url,
        data=json.dumps(body),
        headers={"Content-Type": "application/json"},
        timeout=TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"API error {resp.status_code}: {resp.text[:500]}")
    payload = resp.json()

    for cand in payload.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or {}
            mime = inline.get("mimeType", "")
            data = inline.get("data", "")
            if mime.startswith("image/") and data:
                return base64.b64decode(data)
    raise RuntimeError("no image data in Gemini response")
