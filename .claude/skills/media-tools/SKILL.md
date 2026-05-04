---
name: media-tools
description: Two CLI tools for image generation + vision analysis using goclaw's provider-chain pattern. `create_image` generates images via 7-provider chain (ChatGPT-OAuth/Codex, OpenRouter, Gemini, OpenAI, MiniMax, DashScope, BytePlus) — first available credential wins (OAuth session OR API key), embeds prompt into PNG tEXt metadata, saves to date-folder workspace. The ChatGPT-OAuth provider reads from `~/.codex/auth.json` so a ChatGPT Plus / Codex login works without any API key. `read_image` analyzes images via 4-provider vision chain (OpenRouter, Gemini, Anthropic, DashScope) — accepts file path. Supports `--prompt-file` for long/multi-line prompts, auto UTF-8 stdout, `.env` auto-load, and `--list-providers` diagnostic. Use when Claude needs to generate images or run vision analysis with a specific provider rather than relying on Claude's built-in image understanding.
license: MIT
allowed-tools:
  - Bash
  - Read
---

# Media Tools

Python ports of goclaw's `create_image` and `read_image` tools. Faithful provider-chain pattern: priority order, skip-if-no-key, first-success-wins, cascade-on-failure.

## Setup

```bash
.claude/skills/.venv/Scripts/python.exe -m pip install -r .claude/skills/media-tools/requirements.txt
```

## API keys (env vars)

Set whichever providers you have keys for. Chain skips providers without keys.

```powershell
# Image generation
$env:OPENROUTER_API_KEY = "..."   # OpenRouter (aggregator, OpenAI-compat)
$env:GEMINI_API_KEY     = "..."   # Google AI Studio
$env:OPENAI_API_KEY     = "..."   # OpenAI gpt-image
$env:MINIMAX_API_KEY    = "..."   # MiniMax image-01
$env:DASHSCOPE_API_KEY  = "..."   # Alibaba Qwen / Wan2.6
$env:BYTEPLUS_API_KEY   = "..."   # ByteDance Seedream

# Vision (some keys overlap with image gen)
$env:ANTHROPIC_API_KEY  = "..."   # Anthropic Claude vision

# Optional API base overrides (for proxies / regional endpoints)
$env:OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
$env:OPENAI_API_BASE     = "https://api.openai.com/v1"
# etc — see lib/env_keys.py for full list
```

## create_image

```bash
.claude/skills/.venv/Scripts/python.exe .claude/skills/media-tools/scripts/create_image.py \
  --prompt "a cyberpunk cat in neon rain, ukiyo-e style" \
  --aspect-ratio 16:9 \
  --filename-hint "neon-cat"
```

Options:
- `--prompt` (required) — text description
- `--aspect-ratio` — `1:1` (default) | `3:4` | `4:3` | `9:16` | `16:9`
- `--filename-hint` — kebab-slug for output file (no extension)
- `--workspace` — output dir; default `$WEB_TOOLS_WORKSPACE` or OS temp
- `--provider` — force a specific provider (skip chain): `chatgpt_oauth|openrouter|gemini|openai|minimax|dashscope|byteplus`
- `--provider-order` — comma-separated chain override (default: `chatgpt_oauth,openrouter,gemini,openai,minimax,dashscope,byteplus`)
- `--reference-image PATH` — seed generation with a reference image (PNG/JPG/WEBP). Repeatable, max 4. Supported by `chatgpt_oauth`, `gemini`, `openai`; chain auto-skips others when refs are present.

Output saved to `<workspace>/generated/<YYYY-MM-DD>/<name>.png` with prompt embedded in PNG `tEXt` metadata.

### Reference-image example (image-to-image / restyle / character-consistency)

```bash
.claude/skills/.venv/Scripts/python.exe .claude/skills/media-tools/scripts/create_image.py \
  --prompt "Same character, now wearing a red trench coat, neon Tokyo street at night" \
  --reference-image ./character.png \
  --aspect-ratio 9:16
```

## read_image

```bash
.claude/skills/.venv/Scripts/python.exe .claude/skills/media-tools/scripts/read_image.py \
  --path "C:/path/to/image.png" \
  --prompt "Describe this image in detail. What text appears?"
```

Options:
- `--prompt` (required) — what to ask about the image
- `--path` (required) — local image file (jpg/png/gif/webp/bmp, ≤10MB)
- `--provider` — force specific provider: `openrouter|gemini|anthropic|dashscope`
- `--provider-order` — comma-separated chain (default: `openrouter,gemini,anthropic,dashscope`)
- `--max-tokens` — response max tokens (default 1024)

## Patterns ported from goclaw

| Pattern                                          | goclaw source                       | skill file                  |
| ------------------------------------------------ | ----------------------------------- | --------------------------- |
| Provider chain (priority + skip-no-key + first-success) | `media_provider_chain.go`     | `lib/chain.py`              |
| OpenRouter image (OpenAI-compat + modalities)    | `create_image.go:callImageGenAPI`   | `lib/providers/openrouter_image.py` |
| Gemini image (native generateContent + responseModalities) | `create_image.go:callGeminiNativeImageGen` | `lib/providers/gemini_image.py` |
| OpenAI image (`/images/generations`)             | `create_image.go:callStandardImageGenAPI` | `lib/providers/openai_image.py` |
| MiniMax image (`/image_generation`)              | `create_image_minimax.go`           | `lib/providers/minimax_image.py` |
| DashScope image (async task polling)             | `create_image_dashscope.go`         | `lib/providers/dashscope_image.py` |
| BytePlus Seedream (`/api/v3/images/generations` + URL download) | `create_image_byteplus.go` | `lib/providers/byteplus_image.py` |
| Vision providers (4-way chain)                   | `read_image.go` + provider Chat()   | `lib/providers/*_vision.py` |
| PNG tEXt prompt embedding                        | `pngEmbedPrompt`                    | `lib/png_metadata.py`       |
| Date-folder workspace + sanitized filename       | `mediaFileName`                     | `lib/filename.py`           |

## Aspect-ratio mapping

Each provider has its own size convention; the skill maps `--aspect-ratio` to each:

| aspect | dashscope | byteplus | minimax/openrouter/gemini |
|---|---|---|---|
| 1:1   | 1024*1024 | 1024x1024 | 1:1 (passed through) |
| 16:9  | 1280*720  | 1280x720  | 16:9 |
| 9:16  | 720*1280  | 720x1280  | 9:16 |
| 4:3   | 1024*768  | 1024x768  | 4:3 |
| 3:4   | 768*1024  | 768x1024  | 3:4 |
