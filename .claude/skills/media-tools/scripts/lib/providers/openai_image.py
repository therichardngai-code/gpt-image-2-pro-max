"""OpenAI image generation — port of create_image.go:callStandardImageGenAPI.

Standard /images/generations endpoint with response_format=b64_json.
Used for OpenAI gpt-image and any compatible provider that follows the
DALL-E API shape.
"""

import base64
import json
from typing import Any

import requests

TIMEOUT_SECONDS = 120


def generate(api_key: str, api_base: str, model: str,
             params: dict[str, Any]) -> bytes:
    prompt = params.get("prompt", "")
    body = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "response_format": "b64_json",
    }
    url = api_base.rstrip("/") + "/images/generations"
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

    data = (resp.json().get("data") or [])
    if not data or not data[0].get("b64_json"):
        raise RuntimeError("no image data in response")
    return base64.b64decode(data[0]["b64_json"])
