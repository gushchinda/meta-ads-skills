---
name: generate-creatives
description: Generate Meta-ready ad creatives (images) with Google Nano Banana (gemini-2.5-flash-image). Use when the user asks to generate creatives, make ads, build creatives for a client, "generate N variations", or invokes /generate-creatives. Enforces Meta sizing, concept+variation folder layout, and a mandatory visual verification pass for text rendering.
---

# Generate Creatives (Nano Banana)

Generates ad-ready static creatives for any client, using a concept+variations prompt library and Google's `gemini-2.5-flash-image` model. **Every generated image MUST be visually verified for text correctness — Nano Banana frequently mangles long copy, cursive handwriting, and uncommon words.**

## Commands

```
/generate-creatives <client> <campaign>                      # generate everything in <client>/prompts.json
/generate-creatives <client> <campaign> --slug <slug>        # one concept (all variations)
/generate-creatives <client> <campaign> --variation 2,3      # only specific variations across concepts
/generate-creatives <client> <campaign> --names 01_slug,02_slug   # explicit names
/generate-creatives <client> <campaign> --force              # overwrite existing
```

If no prompts file exists yet, this skill walks the user through drafting one first (see "Bootstrapping a new client" below).

## Prerequisites

- `GEMINI_API_KEY` in `.env` (Google AI Studio key)
- `.venv` with `playwright` (for reference scraping if needed) — `python3 -m venv .venv && .venv/bin/pip install playwright`
- `curl` (used by the generator for SSL-friendly POSTs)

## Meta sizing rules

| Placement | Aspect | Pixels (min) | Use case |
|-----------|--------|--------------|----------|
| Stories / Reels (FB + IG) | **9:16** | 1080×1920 | Default for storyboard-style vertical ads |
| Feed (square) | 1:1 | 1080×1080 | Universal fallback |
| Feed (vertical) | **4:5** | 1080×1350 | Higher feed real estate, recommended for feed |
| Right column | 1.91:1 | 1200×628 | Old format, rarely used |

**Default to 9:16 for storyboard / text-heavy / vertical-first creatives.** Use 4:5 for product photo / lifestyle. Use 1:1 only if explicitly requested.

Nano Banana aspect ratio is set in the generator script's `generationConfig.imageConfig.aspectRatio`. Supported values: `"1:1"`, `"3:4"`, `"4:3"`, `"9:16"`, `"16:9"`. To produce 4:5, generate at 9:16 and crop, or use 1:1 (Nano Banana doesn't have native 4:5).

## Folder layout (enforced)

**Local repo:**
```
<client>/
  prompts.json
  creatives/
    <campaign>/                       # e.g. clarity_based, painpoint, social_proof
      01_<concept_slug>.png            # variation 1 of concept
      02_<concept_slug>.png            # variation 2
      03_<concept_slug>.png            # variation 3
      ...
  references/                          # competitor scrapes / inspiration
    01_<id>.mp4
    ...
```

**Google Drive (`<DRIVE>/<client>/`, where `<DRIVE>` is the client media root set via config/env):**
```
meta/
  for_testing/
    images/<campaign>/NN_<slug>.png
    videos/<campaign>/NN_<slug>.mp4
references/
  <reference files>
```

**Never mix references with deliverables.** Never use per-concept subfolders for the generated creatives — flat under the campaign name.

## prompts.json schema

```json
{
  "style_brief": "<paragraph describing visual & copy direction>",
  "common_constraints": "<aspect ratio, text-rendering rules, no logos, etc.>",
  "campaign": "<campaign_name>",
  "concepts": [
    {
      "slug": "<snake_case_concept_name>",
      "description": "<one-line concept hook>",
      "variations": [
        "<full prompt for variation 1>",
        "<full prompt for variation 2>",
        "<full prompt for variation 3>"
      ]
    }
  ]
}
```

Each variation prompt should:
- Restate the 9:16 / size constraint
- Specify exact text quotes (in single quotes inside the prompt)
- Include the rule: "ALL TEXT MUST RENDER PERFECTLY — short words only"
- Keep body copy SHORT (Nano Banana mangles paragraphs)
- Specify the visual treatment (palette, photo setting, typography style)

## Pipeline

### 1. Read or draft prompts.json

If `<client>/prompts.json` exists → load it, list concepts and variation counts, ask which to generate.

If not → walk the user through brief:
1. Reference style? (existing client's references/, competitor scrape, or text description)
2. Target audience and product positioning
3. Number of concepts (typical 5-10)
4. Variations per concept (typical 3)
5. Write `<client>/prompts.json` using the schema above

If references exist, **Read** them with the Read tool to inform the style brief.

### 2. Generate

```bash
.venv/bin/python scripts/gen_nano_banana.py [--slug ... | --variation ... | --names ... | --force]
```

The script:
- Reads `<client>/prompts.json` (see `examples/prompts.example.json` for the schema; pass `--prompts <path>` if extended later)
- Writes PNGs into `<client>/creatives/<campaign>/NN_<slug>.png`
- Skips files that already exist unless `--force`
- Streams per-file progress with byte size

If a generation **fails** (`No image data in response` or `No candidates`):
- Usually content moderation or one-off API issue → retry once
- If still failing → simplify the prompt (remove anything that could be flagged: figures in dark scenes, etc.)

### 3. VERIFY (mandatory — do not skip)

For **every** generated PNG, use the Read tool on the file path (Read renders images visually for you). For each one, check:

| Check | What to look for |
|-------|------------------|
| Headline text | Spelled exactly as in the prompt? Missing/duplicate letters? |
| Body copy | Every word readable? No fabricated AI words? |
| CTA button | Button text matches prompt? |
| Layout | Hierarchy makes sense? Text contrast OK? |

Report findings as a table: ✓ clean / ⚠ minor issue (note specifics) / ✗ unusable.

### 4. Regenerate any problems

For each ⚠/✗ creative:

**First attempt: retry as-is.** Nano Banana has randomness; same prompt often produces a clean render the next time. Use `--force --names <name>`.

**If still bad after retry: edit the prompt** in `prompts.json` and regenerate. Common fixes:

| Symptom | Fix |
|---------|-----|
| Long word mangled (e.g. "DISCONNECTION" → "DISCONETION") | Swap for shorter synonym ("DRIFTING APART", "DISTANCE") |
| Body paragraph turns to gibberish | Cut to 1-2 short sentences |
| Cursive handwriting unreadable | Specify "NEAT PRINTED BLOCK LETTERS, no cursive" |
| Phone screen text glitched in POV shot | "Phone fills 75% of frame, VERY LARGE message text" |
| Repeated word ("how how", "ask the ask") | Reword to avoid repeated short words |
| Word "AVOIDING" / "CHOOSING" loses letters | Use "HIDING FROM" / "PICKING" |

Always re-verify after each regeneration round.

### 5. Mirror to Google Drive

Drive is locally synced to `<DRIVE>/<client>/` — `<DRIVE>` is the client media root, set via config/env (e.g. a Drive-for-desktop mount path).

```bash
CLIENT=example
CAMPAIGN=clarity_based
DRIVE="<DRIVE>/$CLIENT"
mkdir -p "$DRIVE/meta/for_testing/images/$CAMPAIGN"
rm -f "$DRIVE/meta/for_testing/images/$CAMPAIGN"/*.png
cp "$CLIENT/creatives/$CAMPAIGN"/*.png "$DRIVE/meta/for_testing/images/$CAMPAIGN/"
```

(For first-time client folder creation, also create `<DRIVE>/<client>/` and `<DRIVE>/<client>/references/` via the Drive MCP `create_file` with `application/vnd.google-apps.folder` MIME type.)

### 6. Report

Concise summary to the user:
- N creatives generated, M campaign, K variations per concept
- Quality: X clean / Y borderline (list)
- Drive location URL (folder ID)
- Suggest regen of any borderline via `--names`

## Nano Banana failure modes (memorized)

These are confirmed weak spots — design prompts to avoid them:

1. **Long compound words** ("DISCONNECTION", "AVOIDING", "CHOOSING") frequently lose letters. Use shorter forms.
2. **Body paragraphs > 2 sentences** become hallucinated nonsense. Keep body ≤ 2 short lines.
3. **Cursive handwriting** is barely legible at small sizes. Specify "PRINTED BLOCK LETTERS" explicitly.
4. **Small text in mockups** (phone screens, billboards from a distance) → spell out "phone fills 70-75% of frame", "text must be very large".
5. **POV photos** make any text inside the held object small → same fix.
6. **Brand/app names** with unusual spelling get mangled (e.g. "AcmeApp" → "AcmeAop"). Use the name minimally; rely on CTA buttons rather than in-image branding.

## Output contract

When done, post:
- Drive folder link (clickable)
- Local path
- Final clean/borderline tally
- Names of any borderline creatives, with the one-line reason
