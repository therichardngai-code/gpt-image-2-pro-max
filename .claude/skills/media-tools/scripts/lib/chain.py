"""Provider chain orchestrator — port of goclaw media_provider_chain.go.

Resolves the ordered provider chain by intersecting:
  1. Requested priority order (or default for image / vision)
  2. Providers with API keys present in env

Tries each in order; on success, returns the result. On failure, logs and
cascades to the next. Returns ChainError if all providers fail or none
configured.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable

from .env_keys import (
    IMAGE_DEFAULT_MODELS,
    IMAGE_PROVIDER_PRIORITY,
    VISION_DEFAULT_MODELS,
    VISION_PROVIDER_PRIORITY,
    get_api_base,
    get_api_key,
    get_provider_order_override,
    has_credentials,
)


@dataclass
class ChainResult:
    data: bytes        # image bytes (image gen) or text-encoded bytes (vision)
    provider: str
    model: str


class ChainError(Exception):
    """Raised when no provider succeeds or no providers configured."""


# Provider call signature: (api_key, api_base, model, params) -> bytes
ProviderFn = Callable[[str, str, str, dict], bytes]


def resolve_chain(
    kind: str,                          # "image" or "vision"
    requested_order: list[str] | None,  # CLI override or None for default
    forced_provider: str | None,        # --provider X to force a single one
) -> list[str]:
    """Return ordered provider names with API keys configured.

    Filters out providers without a key (matches goclaw skip-if-no-key).
    Forced provider bypasses the chain — single entry, even if no key (so
    we surface a clear error instead of silent skip).
    """
    if forced_provider:
        return [forced_provider]
    default = (
        IMAGE_PROVIDER_PRIORITY if kind == "image" else VISION_PROVIDER_PRIORITY
    )
    # CLI flag wins over env var wins over built-in default.
    order = (
        requested_order
        or get_provider_order_override(kind)
        or default
    )
    return [p for p in order if has_credentials(p)]


def execute_chain(
    kind: str,
    chain: list[str],
    registry: dict[str, ProviderFn],
    params: dict,
    model_override: str = "",
) -> ChainResult:
    """Try each provider in order until one succeeds. Match goclaw cascade."""
    if not chain:
        order = (IMAGE_PROVIDER_PRIORITY if kind == "image"
                 else VISION_PROVIDER_PRIORITY)
        hints = []
        for p in order:
            if p == "chatgpt_oauth":
                hints.append("chatgpt_oauth (run scripts/chatgpt_oauth_login.py)")
            else:
                hints.append(f"{p.upper()}_API_KEY")
        raise ChainError(
            f"No {kind} provider configured. Set up at least one of: "
            + ", ".join(hints)
        )

    defaults = (
        IMAGE_DEFAULT_MODELS if kind == "image" else VISION_DEFAULT_MODELS
    )

    last_err: Exception | None = None
    for name in chain:
        fn = registry.get(name)
        if fn is None:
            print(f"chain: unknown provider {name!r}, skipping",
                  file=sys.stderr)
            continue
        # chatgpt_oauth keeps creds on disk, not env — skip the env-key check.
        if name != "chatgpt_oauth":
            api_key = get_api_key(name)
            if not api_key:
                print(f"chain: {name} has no API key, skipping", file=sys.stderr)
                continue
        else:
            api_key = ""  # provider reads token from disk
        api_base = get_api_base(name)
        model = model_override or defaults.get(name, "")
        try:
            print(f"chain: trying {name} (model={model})", file=sys.stderr)
            data = fn(api_key, api_base, model, params)
            return ChainResult(data=data, provider=name, model=model)
        except Exception as e:                                    # noqa: BLE001
            last_err = e
            print(f"chain: {name} failed: {e}", file=sys.stderr)
            continue

    raise ChainError(
        f"all {kind} providers failed: {last_err}" if last_err
        else f"no {kind} providers were callable"
    )
