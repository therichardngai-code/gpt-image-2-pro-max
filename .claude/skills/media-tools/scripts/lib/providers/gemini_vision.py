"""Gemini vision — native generateContent with inlineData parts.

Each image is passed as `{inlineData: {mimeType, data}}` part alongside a
text part. Response text comes from candidates[0].content.parts[].text.
"""

import json
from typing import Any

import requests

TIMEOUT_SECONDS = 120


def analyze(api_key: str, api_base: str, model: str,
            params: dict[str, Any]) -> bytes:
    prompt = params.get("prompt", "")
    images = params.get("images") or []
    max_tokens = params.get("max_tokens", 1024)
    temperature = params.get("temperature", 0.3)

    native_base = api_base.rstrip("/")
    if native_base.endswith("/openai"):
        native_base = native_base[:-len("/openai")]

    parts: list = [{"text": prompt}]
    for img in images:
        parts.append({
            "inlineData": {
                "mimeType": img["mime_type"],
                "data": img["data_b64"],
            },
        })

    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }
    url = f"{native_base}/models/{model}:generateContent?key={api_key}"
    resp = requests.post(
        url,
        data=json.dumps(body),
        headers={"Content-Type": "application/json"},
        timeout=TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"API error {resp.status_code}: {resp.text[:500]}")

    out: list[str] = []
    for cand in resp.json().get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            if text := part.get("text"):
                out.append(text)
    if not out:
        raise RuntimeError("no text in Gemini vision response")
    return "".join(out).encode("utf-8")
