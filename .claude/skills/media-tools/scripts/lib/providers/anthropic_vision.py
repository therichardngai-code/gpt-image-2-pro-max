"""Anthropic Claude vision — Messages API with image content blocks.

Endpoint: POST {api_base}/v1/messages
Auth: x-api-key header (NOT Authorization Bearer)
Image format: {type: "image", source: {type: "base64", media_type, data}}
"""

import json
from typing import Any

import requests

TIMEOUT_SECONDS = 120
ANTHROPIC_VERSION = "2023-06-01"


def analyze(api_key: str, api_base: str, model: str,
            params: dict[str, Any]) -> bytes:
    prompt = params.get("prompt", "")
    images = params.get("images") or []
    max_tokens = params.get("max_tokens", 1024)
    temperature = params.get("temperature", 0.3)

    content: list = []
    for img in images:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["mime_type"],
                "data": img["data_b64"],
            },
        })
    content.append({"type": "text", "text": prompt})

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": content}],
    }
    url = api_base.rstrip("/") + "/v1/messages"
    resp = requests.post(
        url,
        data=json.dumps(body),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        timeout=TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"API error {resp.status_code}: {resp.text[:500]}")

    out: list[str] = []
    for block in resp.json().get("content") or []:
        if block.get("type") == "text" and block.get("text"):
            out.append(block["text"])
    if not out:
        raise RuntimeError("no text in Anthropic vision response")
    return "".join(out).encode("utf-8")
