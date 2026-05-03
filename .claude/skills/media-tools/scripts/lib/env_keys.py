"""API key + base URL resolution from environment variables.

Equivalent of goclaw's `config_secrets` table — stores encrypted keys per
tenant. In a single-user skill, env vars play that role.

Each provider has:
  - <PROVIDER>_API_KEY  (required to enable the provider in the chain)
  - <PROVIDER>_API_BASE (optional, falls back to vendor default)

Default API bases match goclaw's NormalizeProviderAPIBase shipping defaults.

Auto-loads `.env` once on first import so every entry script + provider
gets keys without each having to call load() explicitly.
"""

import os

from .dotenv_loader import load as _load_dotenv

# Single-shot .env load. os.environ.setdefault() means OS env vars win over
# the file (safe for CI), so re-importing this module is harmless.
_load_dotenv()

# Vendor default API bases — match goclaw's provider defaults.
DEFAULT_API_BASES = {
    "openrouter":     "https://openrouter.ai/api/v1",
    "openai":         "https://api.openai.com/v1",
    "gemini":         "https://generativelanguage.googleapis.com/v1beta",
    "anthropic":      "https://api.anthropic.com",
    "minimax":        "https://api.minimaxi.chat/v1",
    "dashscope":      "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "byteplus":       "https://ark.ap-southeast.bytepluses.com/api/v3",
    "chatgpt_oauth":  "https://chatgpt.com/backend-api",
}

# Default models — match goclaw imageGenModelDefaults / visionModelDefaults.
# chatgpt_oauth's outer parent model defaults to gpt-5.4; the image model
# (gpt-image-2 / gpt-image-1.5) is whitelisted in chatgpt_oauth_image.py.
IMAGE_DEFAULT_MODELS = {
    "openrouter":    "google/gemini-2.5-flash-image",
    "openai":        "gpt-image-1.5",
    "gemini":        "gemini-2.5-flash-image",
    "minimax":       "image-01",
    "dashscope":     "wan2.6-image",
    "byteplus":      "seedream-5-0-260128",
    "chatgpt_oauth": "gpt-5.4",
}
VISION_DEFAULT_MODELS = {
    "openrouter": "google/gemini-2.5-flash-image",
    "gemini":     "gemini-2.5-flash",
    "anthropic":  "claude-sonnet-4-6",
    "dashscope":  "qwen3-vl",
}

# Goclaw's chain priority orders. chatgpt_oauth goes first when present —
# matches goclaw routing (OAuth-backed providers preferred over static keys
# when the user has a Codex session).
IMAGE_PROVIDER_PRIORITY = [
    "chatgpt_oauth",
    "openrouter", "gemini", "openai", "minimax", "dashscope", "byteplus",
]
VISION_PROVIDER_PRIORITY = [
    "openrouter", "gemini", "anthropic", "dashscope",
]


def get_api_key(provider: str) -> str:
    """Return the API key for a provider, or empty string if unset.

    chatgpt_oauth: returns "" — credentials live on disk, not env.
    """
    if provider == "chatgpt_oauth":
        return ""
    return os.environ.get(f"{provider.upper()}_API_KEY", "").strip()


def get_api_base(provider: str) -> str:
    """Return the API base URL — env override or vendor default."""
    override = os.environ.get(f"{provider.upper()}_API_BASE", "").strip()
    if override:
        return override
    return DEFAULT_API_BASES.get(provider, "")


def has_credentials(provider: str) -> bool:
    """True if the provider has credentials configured.

    For env-key providers: the env var must be set.
    For chatgpt_oauth: a saved session must exist on disk.
    """
    if provider == "chatgpt_oauth":
        # Local import to keep this module dependency-light.
        from .chatgpt_oauth_token import has_valid_session
        return has_valid_session()
    return bool(get_api_key(provider))


def get_provider_order_override(kind: str) -> list[str] | None:
    """Read user-defined chain order from env vars.

    MEDIA_TOOLS_IMAGE_ORDER  / MEDIA_TOOLS_VISION_ORDER override the
    built-in priority. MEDIA_TOOLS_PROVIDER_ORDER applies to both kinds
    (lower precedence than the kind-specific vars).

    Format: comma-separated provider names, e.g. "gemini,openrouter,openai".
    Returns None if no override set.
    """
    specific_key = (
        "MEDIA_TOOLS_IMAGE_ORDER" if kind == "image"
        else "MEDIA_TOOLS_VISION_ORDER"
    )
    raw = (
        os.environ.get(specific_key)
        or os.environ.get("MEDIA_TOOLS_PROVIDER_ORDER")
        or ""
    ).strip()
    if not raw:
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]
