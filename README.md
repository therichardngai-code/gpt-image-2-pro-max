# gpt-image-2-pro-max — Claude Code skill

Production prompt-engineering skill for **GPT-Image-2 / OpenAI image generation**. Pairs a `media-designer` agent with a hosted searchable corpus of 7,030+ community-vetted prompts.

We collect high-quality prompts and image examples for GPT-Image-2 across portraits, posters, character sheets, UI mockups, and community experiments.

Most cases in this repository are curated from X/Twitter, creator communities, public demos, and shared experiments.

If you find this useful, consider giving it a star. ⭐

## What you get

- **Agent**: `.claude/agents/media-designer.md` — diagnoses your brief, picks a mood-aligned base, refactors it into a parameterised template, and returns a paste-ready prompt.
- **Skill + tool**: `.claude/skills/gpt-image-2-pro-max/` — `search.py` thin client over a hosted backend (BM25 search across 10 facet vocabularies).
- **Companion skill**: `.claude/skills/media-tools/` — optional CLI for actually generating images (multi-provider chain: OpenRouter → Gemini → OpenAI gpt-image-2 → MiniMax → DashScope → BytePlus, or your ChatGPT Plus session). See its own `README.md` for setup.
- **Hosted backend** (already live): `https://gpt-image-2-prompts.goclawoffice.com`
  - Thousands of indexed prompts with BM25 search and reference images
  - Rate-limited per IP for fair use; a small set of guards keeps the corpus available to everyone (origin/UA gate, ≥3-token queries, daily budgets, edge cache)

## Install

Drop the `.claude/` folder into your Claude Code project. No build step, no API key, no install.

```bash
# Clone or copy
cp -r .claude /path/to/your-project/

# Verify the skill is discoverable
ls /path/to/your-project/.claude/skills/gpt-image-2-pro-max/
```

Python 3.8+ required (uses stdlib only — no pip install).

## Usage

In Claude Code, invoke the skill directly or let the `media-designer` agent drive:

```bash
# Free-text search (BM25 + tag-aware ranking; needs ≥3 descriptive tokens)
python .claude/skills/gpt-image-2-pro-max/scripts/search.py "luxury shoe ad cream pastel" -n 5

# Narrow by output shape, require a reference image
python .claude/skills/gpt-image-2-pro-max/scripts/search.py "moody cinematic portrait 35mm" \
    --shape portrait --has-image -n 3

# Show full prompt body for every rank (top-1 is always full)
python .claude/skills/gpt-image-2-pro-max/scripts/search.py "neon ui dashboard" --full -n 3

# Persist top hits as a markdown reference deck (with embedded images)
python .claude/skills/gpt-image-2-pro-max/scripts/search.py "anime portrait" --persist refs.md

# Browse the controlled vocabulary (10 facets: subjects, styles, lighting,
# cameras, moods, palettes, compositions, mediums, techniques, usecases)
python .claude/skills/gpt-image-2-pro-max/scripts/search.py --list facets
python .claude/skills/gpt-image-2-pro-max/scripts/search.py --list moods
python .claude/skills/gpt-image-2-pro-max/scripts/search.py --list palettes
```

The agent profile is canonical — its `diagnose → search → pick → refactor → resolve` loop is how good prompts get built.

## Attribution

Each record carries its original tweet/X link in the `tweet` field. The agent profile makes attribution mandatory in every output. Prompt content belongs to the original authors.

### Credits

Big thanks to the **[EvoLinkAI/awesome-gpt-image-2-prompts](https://github.com/EvoLinkAI/awesome-gpt-image-2-prompts)** community for curating and openly sharing a large portion of the prompt corpus that seeds this skill. Their work is what makes this useful out of the box.

If you use this skill, please also star their repo — most prompts here trace back to authors they collected and credited first.

The `media-tools` companion skill's **ChatGPT / Codex OAuth image-generation** path is a Python port of the pattern landed in **[nextlevelbuilder/goclaw#1002](https://github.com/nextlevelbuilder/goclaw/pull/1002)** — same priority-chain idea (skip provider if no key → first success wins → cascade on failure), same OAuth-token reuse trick so users with an existing ChatGPT Plus subscription don't need a separate API key. Credit and gratitude to the goclaw maintainers.

## License

Prompt content belongs to the original authors (Twitter/X handles in each record). Skill code is MIT.
