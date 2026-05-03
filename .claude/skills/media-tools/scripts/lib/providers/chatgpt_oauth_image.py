"""ChatGPT OAuth (Codex Responses API) image generation.

Port of goclaw/internal/providers/codex_native_image.go. Calls the private
ChatGPT backend at POST {api_base}/codex/responses with the native
image_generation tool. Auth is OAuth Bearer (NOT a static API key).

Wire format (matches goclaw exactly):
- stream:true (server rejects false)
- instructions populated (server rejects empty)
- tool_choice forces image_generation
- tools[0].model is the image model (gpt-image-2 default; gpt-image-1.5 legacy)
- outer "model" is the parent LLM (defaults to gpt-5.4)

Headers:
- Authorization: Bearer <token>
- OpenAI-Beta: responses=v1
- Content-Type: application/json

Response is SSE; parse `response.output_item.done` (image_generation_call)
or walk `response.completed`.output[]. Image is base64 in item.result.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import requests

from ..chatgpt_oauth_token import DEFAULT_API_BASE, get_access_token

TIMEOUT_SECONDS = 600  # gpt-image-2 is slow; matches goclaw chain default
DEFAULT_PARENT_MODEL = "gpt-5.4"  # matches goclaw codex.go defaultModel
DEFAULT_IMAGE_MODEL = "gpt-image-2"
ALLOWED_IMAGE_MODELS = {"gpt-image-2", "gpt-image-1.5"}

INSTRUCTIONS = (
    "Generate an image matching the user's description using the "
    "image_generation tool. Return only the image; do not describe it in text."
)


def _validate_image_model(model: str) -> str:
    """Port of goclaw ValidateImageModel — empty → default, else whitelist check."""
    if not model:
        return DEFAULT_IMAGE_MODEL
    if model not in ALLOWED_IMAGE_MODELS:
        raise ValueError(
            f"unsupported image model {model!r}; allowed: "
            f"gpt-image-2 (default), gpt-image-1.5 (legacy)"
        )
    return model


def _size_from_aspect(aspect: str) -> str:
    """Port of goclaw SizeFromAspect — pixel sizes for the image_generation tool."""
    return {
        "16:9": "1792x1024",
        "9:16": "1024x1792",
        "3:4":  "1024x1365",
        "4:3":  "1365x1024",
    }.get(aspect, "1024x1024")


def _build_body(parent_model: str, image_model: str, prompt: str,
                aspect: str, output_format: str) -> dict:
    return {
        "model": parent_model,
        "stream": True,
        "store": False,
        "instructions": INSTRUCTIONS,
        "input": [{
            "role": "user",
            "content": [{"type": "input_text", "text": prompt}],
        }],
        "tools": [{
            "type": "image_generation",
            "action": "generate",
            "model": image_model,
            "output_format": output_format,
            "size": _size_from_aspect(aspect),
        }],
        "tool_choice": {"type": "image_generation"},
    }


def _parse_sse_for_image(stream) -> bytes:
    """Walk SSE lines for the image. Mirrors goclaw parseNativeImageSSE."""
    b64 = ""
    for raw_line in stream.iter_lines():
        if not raw_line:
            continue
        if isinstance(raw_line, bytes):
            try:
                raw_line = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                continue
        if not raw_line.startswith("data: "):
            continue
        payload = raw_line[len("data: "):]
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue

        etype = event.get("type", "")
        if etype == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "image_generation_call" and item.get("result"):
                b64 = item["result"]
        elif etype == "response.completed":
            response = event.get("response") or {}
            for it in response.get("output") or []:
                if it.get("type") == "image_generation_call" and it.get("result"):
                    b64 = it["result"]
        elif etype == "response.failed" or etype == "error":
            err = event.get("response", {}).get("error") or event.get("error") or {}
            msg = err.get("message") or err.get("code") or "unknown error"
            raise RuntimeError(f"Codex Responses API error: {msg}")

    if not b64:
        raise RuntimeError("no image in SSE stream")
    return base64.b64decode(b64)


def generate(api_key_unused: str, api_base: str, model: str,
             params: dict[str, Any]) -> bytes:
    """Generate an image via ChatGPT OAuth.

    `api_key_unused` is the chain interface argument; we ignore it because
    OAuth tokens come from the on-disk session, not env. `model` is the
    parent LLM model (--model flag); image model comes from params['image_model'].
    """
    prompt = params.get("prompt", "")
    if not prompt:
        raise ValueError("prompt is required")

    parent_model = model or DEFAULT_PARENT_MODEL
    image_model = _validate_image_model(params.get("image_model", ""))
    aspect = params.get("aspect_ratio", "1:1")
    output_format = params.get("output_format", "png")

    base = (api_base or DEFAULT_API_BASE).rstrip("/")
    endpoint = f"{base}/codex/responses"

    token = get_access_token()
    body = _build_body(parent_model, image_model, prompt, aspect, output_format)

    resp = requests.post(
        endpoint,
        data=json.dumps(body),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "OpenAI-Beta": "responses=v1",
        },
        stream=True,
        timeout=TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        snippet = resp.text[:500] if hasattr(resp, "text") else ""
        resp.close()
        raise RuntimeError(f"API error {resp.status_code}: {snippet}")
    try:
        return _parse_sse_for_image(resp)
    finally:
        resp.close()
