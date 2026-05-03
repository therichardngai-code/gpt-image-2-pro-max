"""MiniMax image generation — port of create_image_minimax.go.

Endpoint: POST {api_base}/image_generation
Response: data.image_base64[] OR data.image_list[].base64_image
Includes base_resp.status_code error envelope.
"""

import base64
import json
from typing import Any

import requests

TIMEOUT_SECONDS = 120

_VALID_RATIOS = {"1:1", "3:4", "4:3", "9:16", "16:9"}

# Legacy "WIDTH*HEIGHT" → ratio mapping (matches goclaw minimaxImageAspectRatio).
_SIZE_TO_RATIO = {
    "1280*720":  "16:9",
    "720*1280":  "9:16",
    "1024*768":  "4:3",
    "768*1024":  "3:4",
    "1024*1024": "1:1",
}


def _aspect_ratio(params: dict) -> str:
    size = params.get("size", "")
    if size:
        compact = size.replace(" ", "")
        if compact in _SIZE_TO_RATIO:
            return _SIZE_TO_RATIO[compact]
    ratio = params.get("aspect_ratio", "")
    if ratio in _VALID_RATIOS:
        return ratio
    return "1:1"


def generate(api_key: str, api_base: str, model: str,
             params: dict[str, Any]) -> bytes:
    body = {
        "model": model,
        "prompt": params.get("prompt", ""),
        "aspect_ratio": _aspect_ratio(params),
        "response_format": "base64",
    }
    url = api_base.rstrip("/") + "/image_generation"
    resp = requests.post(
        url,
        data=json.dumps(body),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        timeout=TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"API error {resp.status_code}: {resp.text[:500]}")
    payload = resp.json()

    base_resp = payload.get("base_resp") or {}
    if base_resp.get("status_code", 0) != 0:
        raise RuntimeError(
            f"MiniMax API error {base_resp.get('status_code')}: "
            f"{base_resp.get('status_msg', '')}"
        )

    data = payload.get("data") or {}
    b64 = ""
    if data.get("image_base64"):
        b64 = data["image_base64"][0]
    elif data.get("image_list"):
        b64 = data["image_list"][0].get("base64_image", "")
    if not b64:
        raise RuntimeError("no image data in MiniMax response")
    return base64.b64decode(b64)
