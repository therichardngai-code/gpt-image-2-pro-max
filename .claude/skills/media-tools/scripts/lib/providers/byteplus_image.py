"""BytePlus Seedream image generation — port of create_image_byteplus.go.

Synchronous API (no polling). Returns data[].url which we then download.
Endpoint always uses /api/v3/images/generations regardless of the
api_base path suffix (matches goclaw bytePlusMediaBase normalization).
"""

import json
from typing import Any

import requests

TIMEOUT_SECONDS = 120
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024

_RATIO_TO_SIZE = {
    "16:9": "1280x720",
    "9:16": "720x1280",
    "4:3":  "1024x768",
    "3:4":  "768x1024",
    "1:1":  "1024x1024",
}

_VERSIONED_SUFFIXES = ("/api/coding/v3", "/api/v3", "/v3")


def _media_base(api_base: str) -> str:
    """Normalize api_base to .../api/v3 — matches goclaw bytePlusMediaBase."""
    base = api_base.rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[:-len("/chat/completions")]
    for suffix in _VERSIONED_SUFFIXES:
        if base.endswith(suffix):
            return base[:-len(suffix)] + "/api/v3"
    return base + "/api/v3"


def _size_param(params: dict) -> str:
    if size := params.get("size"):
        return size
    ratio = params.get("aspect_ratio", "1:1")
    return _RATIO_TO_SIZE.get(ratio, "1024x1024")


def _download_image(url: str) -> bytes:
    resp = requests.get(url, timeout=TIMEOUT_SECONDS, stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"download error {resp.status_code}: {resp.text[:300]}")
    body = resp.raw.read(MAX_DOWNLOAD_BYTES, decode_content=True)
    if not body:
        raise RuntimeError("empty image download")
    return body


def generate(api_key: str, api_base: str, model: str,
             params: dict[str, Any]) -> bytes:
    body = {
        "model": model,
        "prompt": params.get("prompt", ""),
        "size": _size_param(params),
        "response_format": "url",
    }
    endpoint = _media_base(api_base) + "/images/generations"
    resp = requests.post(
        endpoint,
        data=json.dumps(body),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        timeout=TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"API error {resp.status_code}: {resp.text[:500]}")

    data = resp.json().get("data") or []
    if not data or not data[0].get("url"):
        raise RuntimeError(f"no image URL in BytePlus response: {resp.text[:300]}")
    return _download_image(data[0]["url"])
