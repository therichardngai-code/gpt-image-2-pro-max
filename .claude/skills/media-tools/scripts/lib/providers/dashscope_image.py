"""DashScope (Alibaba) image generation — port of create_image_dashscope.go.

Async API: initial POST returns either synchronous results or a task_id;
on async, poll {base}/api/v1/tasks/{task_id} every 10s up to 30 times
(~5min ceiling). Final result is a URL — download bytes via HTTP GET.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any

import requests

TIMEOUT_SECONDS = 60
POLL_INTERVAL_SECONDS = 10
MAX_POLLS = 30
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024  # 32MB image cap

_RATIO_TO_SIZE = {
    "16:9": "1280*720",
    "9:16": "720*1280",
    "4:3":  "1024*768",
    "3:4":  "768*1024",
    "1:1":  "1024*1024",
}

# Suffixes stripped to derive the real DashScope host from a compat base.
_COMPAT_SUFFIXES = (
    "/compatible-mode/v1", "/compatible-mode",
    "/openai/v1", "/openai", "/v1",
)


def _native_base(api_base: str) -> str:
    base = api_base.rstrip("/")
    for suffix in _COMPAT_SUFFIXES:
        if base.endswith(suffix):
            return base[:-len(suffix)]
    return base


def _size_param(params: dict) -> str:
    if size := params.get("size"):
        return size
    ratio = params.get("aspect_ratio", "1:1")
    return _RATIO_TO_SIZE.get(ratio, "1024*1024")


def _download_image(url: str) -> bytes:
    resp = requests.get(url, timeout=TIMEOUT_SECONDS, stream=True)
    if resp.status_code != 200:
        raise RuntimeError(f"download error {resp.status_code}: {resp.text[:300]}")
    body = resp.raw.read(MAX_DOWNLOAD_BYTES, decode_content=True)
    if not body:
        raise RuntimeError("empty image download")
    return body


def _poll_task(api_key: str, native_base: str, task_id: str) -> bytes:
    url = f"{native_base}/api/v1/tasks/{task_id}"
    print(f"dashscope: task {task_id} started, polling", file=sys.stderr)
    for attempt in range(MAX_POLLS):
        time.sleep(POLL_INTERVAL_SECONDS)
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"poll error {resp.status_code}: {resp.text[:500]}"
            )
        output = (resp.json().get("output") or {})
        status = output.get("task_status", "")
        if status == "SUCCEEDED":
            results = output.get("results") or []
            if results and results[0].get("url"):
                return _download_image(results[0]["url"])
            raise RuntimeError("task succeeded but no image URL")
        if status == "FAILED":
            raise RuntimeError(f"DashScope task {task_id} failed")
        print(f"dashscope: task pending (attempt {attempt+1}, status={status})",
              file=sys.stderr)
    raise RuntimeError(
        f"DashScope task {task_id} timed out after {MAX_POLLS} polls"
    )


def generate(api_key: str, api_base: str, model: str,
             params: dict[str, Any]) -> bytes:
    native_base = _native_base(api_base)
    endpoint = f"{native_base}/api/v1/services/aigc/multimodal-generation/generation"
    body = {
        "model": model,
        "input": {
            "messages": [{"role": "user", "content": params.get("prompt", "")}],
        },
        "parameters": {
            "n": 1,
            "size": _size_param(params),
            "prompt_extend": params.get("prompt_extend", True),
        },
    }
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

    output = (resp.json().get("output") or {})
    if not output:
        raise RuntimeError(f"no output in DashScope response: {resp.text[:300]}")

    # Synchronous result
    results = output.get("results") or []
    if results and results[0].get("url"):
        return _download_image(results[0]["url"])

    task_id = output.get("task_id", "")
    if not task_id:
        raise RuntimeError("no task_id and no results in DashScope response")
    return _poll_task(api_key, native_base, task_id)
