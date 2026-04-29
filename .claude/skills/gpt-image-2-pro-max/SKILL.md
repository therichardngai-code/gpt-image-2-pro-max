---
name: gpt-image-2-pro-max
description: "Production prompt-engineering pipeline for GPT-Image-2 / OpenAI image generation. Pairs a 'media-designer' agent with a hosted searchable corpus of 3,238 community-vetted prompts, decomposed across 10 controlled vocabularies (subjects, styles, lighting, cameras, moods, palettes, compositions, mediums, techniques, usecases). Each record carries: full prompt body, twitter/X attribution link, downloaded reference image. Workflow: agent diagnoses the user brief → searches the corpus → picks a mood-aligned base → refactors the chosen prompt into a parameterised {argument} template → resolves arguments from user intent → returns the final paste-ready prompt with attribution + reference image. Use when the user wants a polished image-generation prompt for ads, posters, product shots, portraits, character sheets, UI mockups, infographics, exploded-view diagrams, or any other GPT-Image-2 / OpenAI image task."
category: ai
keywords: [gpt-image-2, image-prompts, prompt-library, openai-image, ai-image, prompt-engineering, ad-creative, product-photography, media-designer]
metadata:
  author: claudekit
  version: "1.0.0"
  endpoint: "https://gpt-image-2-prompts.goclawoffice.com"
---

# GPT-Image-2 Prompt Library + Media Designer Agent

Two-piece skill:

1. **`scripts/search.py`** — thin HTTP client over a hosted corpus of 3,238 community-vetted prompts. BM25-ranked, tagged across 10 facets.
2. **`agents/media-designer.md`** — agent profile that *uses* the search tool to turn a user brief into a paste-ready GPT-Image-2 prompt.

The tool finds candidates. The agent owns the judgement (which base, which slots to parameterise, which to keep literal, mood/palette fit).

## When to Apply

### Must use
- User wants a GPT-Image-2 / OpenAI image-generation prompt for a real production task (ad, poster, product shot, character sheet, UI mockup, portrait)
- User describes a brief and wants a polished prompt back, not just inspiration
- User is studying how top creators structure prompts and wants attributed examples

### Skip
- User wants the image **rendered** — route to `ai-multimodal` or `ai-artist`
- Task unrelated to image prompts
- User already has a finished prompt and just wants it run

## Recommended Workflow

For any production prompt request:

```
1. Read agents/media-designer.md
2. Run the 6-step workflow it defines
3. Return the 4-block output (Base · Parameterised · Resolved · Rationale)
```

## Hosted backend

```
Endpoint: https://gpt-image-2-prompts.goclawoffice.com
```

Thousands of community-vetted prompts indexed across 10 facets (subjects, styles, lighting, cameras, moods, palettes, compositions, mediums, techniques, usecases). Each record carries the prompt body, attribution, and a reference image. Rate-limited per IP — fair-use friendly, but please don't scrape.

## CLI

```
search.py [query] [--shape SHAPE] [--has-image] [-n N] [--full] [--persist PATH]
```

```bash
# Free-text search (this is what the agent calls)
python scripts/search.py "luxury shoe ecommerce ad cream pastel" -n 5

# Narrow by shape when the brief is specific about format
python scripts/search.py "perfume bottle" --shape ecommerce -n 3

# Persist top hits as a markdown reference deck (with embedded images)
python scripts/search.py "neon ui" --persist plans/neon-refs.md
```

Filter knobs:
- `--shape` — portrait | poster | ui | character | comparison | ecommerce | ad | thumbnail | infographic | comic
- `--has-image` — only records with a reference image
- `-n N` — top N (default 5)
- `--full` — don't truncate prompt body
- `--persist PATH` — write top results to a markdown file with embedded reference images

## Output Anatomy

```
#1  bm25=-15.59  shape=ecommerce
  id    : z9q36mnc
  title : Futuristic Bionic Super Shoe
  author: @<creator>
  tweet : https://x.com/<creator>/status/<tweet_id>
  image : <reference image URL>
  tags  : subjects=product,fashion-item | styles=cinematic | cameras=low-angle |
          moods=luxurious,intense,futuristic | palettes=gold-black |
          techniques=parameterised-template
  prompt:
    Extreme futuristic {argument name="subject" default="cheetah bionic super shoe"} ...
```

## Agent Profile

`.claude/agents/media-designer.md` defines the canonical workflow. Headline contents:

| Section | Purpose |
|---|---|
| Mental model | `brief → diagnose → search → pick (mood-aware) → refactor → resolve → output` |
| Step 1 — Diagnose | Extract product, brand, shape, mood, palette, technique signals from the brief |
| Step 2 — Search | Synthesise tokens, run `search.py "<tokens>" -n 5` |
| Step 3 — Pick | Mood-mismatch rejection table — pastel briefs reject `moody/gritty/dark-amber`, etc. |
| Step 4 — Refactor | Replace product-specifics with `{argument name="X" default="Y"}` slots; keep mood/lighting/style words literal |
| Step 5 — Resolve | Fill slots from user intent; default-fallback when ambiguous; never invent |
| Step 6 — Output | 4 blocks: Base (cite author + tweet) · Parameterised · Resolved · Rationale (≤80 words) |
