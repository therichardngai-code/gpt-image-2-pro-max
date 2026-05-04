"""OpenAI image generation — port of create_image.go:callStandardImageGenAPI.

Two endpoints:
- /images/generations  — text-only (JSON body)
- /images/edits        — text + reference image(s) (multipart form data)

The endpoint is selected by params['reference_images']; presence forces
edits. gpt-image-2 accepts up to 4 reference images via repeated 'image[]'
form fields; older DALL-E models accept only one.
"""

import base64
import json
from typing import Any

import requests

TIMEOUT_SECONDS = 120


def _generations(api_key: str, api_base: str, model: str, prompt: str) -> bytes:
    """Text-only path: POST /images/generations with JSON body."""
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
    return _decode_image(resp)


def _edits(api_key: str, api_base: str, model: str, prompt: str,
           ref_images: list[dict]) -> bytes:
    """Reference-image path: POST /images/edits as multipart form.

    For gpt-image-2 we pass each ref as a separate 'image[]' part so the
    server treats them as a set. Falls back to a single 'image' part for
    older models that only accept one reference.
    """
    url = api_base.rstrip("/") + "/images/edits"
    field = "image[]" if len(ref_images) > 1 else "image"
    files = [
        (field, (ref["name"], ref["bytes"], ref["mime"]))
        for ref in ref_images
    ]
    data = {
        "model": model,
        "prompt": prompt,
        "n": "1",
        "response_format": "b64_json",
    }
    resp = requests.post(
        url,
        data=data,
        files=files,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=TIMEOUT_SECONDS,
    )
    return _decode_image(resp)


def _decode_image(resp: requests.Response) -> bytes:
    if resp.status_code != 200:
        raise RuntimeError(f"API error {resp.status_code}: {resp.text[:500]}")
    data = (resp.json().get("data") or [])
    if not data or not data[0].get("b64_json"):
        raise RuntimeError("no image data in response")
    return base64.b64decode(data[0]["b64_json"])


def generate(api_key: str, api_base: str, model: str,
             params: dict[str, Any]) -> bytes:
    prompt = params.get("prompt", "")
    ref_images = params.get("reference_images") or []
    if ref_images:
        return _edits(api_key, api_base, model, prompt, ref_images)
    return _generations(api_key, api_base, model, prompt)
