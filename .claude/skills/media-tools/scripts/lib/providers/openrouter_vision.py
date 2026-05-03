"""OpenRouter vision — OpenAI-compat /chat/completions with image_url parts.

Goclaw routes vision through provider.Chat() with images in the message;
OpenRouter follows OpenAI's vision shape: content is an array of
{type: "text"} and {type: "image_url"} parts.
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

    content: list = [{"type": "text", "text": prompt}]
    for img in images:
        url = f"data:{img['mime_type']};base64,{img['data_b64']}"
        content.append({"type": "image_url", "image_url": {"url": url}})

    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
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

    choices = resp.json().get("choices") or []
    if not choices:
        raise RuntimeError("no choices in response")
    text = (choices[0].get("message") or {}).get("content") or ""
    if not text:
        raise RuntimeError("empty vision response")
    return text.encode("utf-8")
