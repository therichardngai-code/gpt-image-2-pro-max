"""OpenRouter image generation — port of create_image.go:callImageGenAPI.

OpenAI-compatible /chat/completions endpoint with `modalities: ["image","text"]`.
Image arrives either in choices[0].message.images[].image_url.url (data URL)
or in a multipart content array.
"""

import base64
import json
from typing import Any

import requests

TIMEOUT_SECONDS = 120


def _decode_data_url(data_url: str) -> bytes:
    if ";base64," not in data_url:
        raise ValueError("not a base64 data URL")
    return base64.b64decode(data_url.split(";base64,", 1)[1])


def _parse_image_response(body: dict) -> bytes:
    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("no choices in response")
    msg = choices[0].get("message") or {}

    # Try images array first (OpenRouter format)
    for img in msg.get("images") or []:
        url = (img.get("image_url") or {}).get("url") or ""
        if url:
            try:
                return _decode_data_url(url)
            except Exception:
                pass

    # Try multipart content array (some providers return parts)
    content = msg.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                url = (part.get("image_url") or {}).get("url") or ""
                if url:
                    try:
                        return _decode_data_url(url)
                    except Exception:
                        pass

    raise RuntimeError("no image data found in response")


def generate(api_key: str, api_base: str, model: str,
             params: dict[str, Any]) -> bytes:
    prompt = params.get("prompt", "")
    aspect_ratio = params.get("aspect_ratio", "1:1")

    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
    }
    if aspect_ratio and aspect_ratio != "1:1":
        body["image_config"] = {"aspect_ratio": aspect_ratio}

    url = api_base.rstrip("/") + "/chat/completions"
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
    return _parse_image_response(resp.json())
