---
name: creative-monitor
description: Use when the user asks what new creatives are waiting to be launched, wants a daily "new creatives" check per project, or asks "что нового в папке", "what's not uploaded yet", "scan for new creatives", "creative status". Scans the project's creative folder and compares it to the ad account — not to folder names or manifests.
---

# Creative monitor

Finds creatives that sit in a project's folder but are **not yet in its Meta ad account**.

## Core rule: scan, don't trust conventions

A file is "new" when its normalized name is absent from the account's **ads, ad videos and ad images**.
Do not answer from folder names (`_new/`), manifests or file dates:
- people drop files wherever is convenient, so a convention misses batches;
- synced drives re-stamp dates on re-sync, so yesterday's batch looks like today's (`--days` is a filter only).

This relies on the shared convention **ad name = file name without extension** (`creative-testing` enforces it).

Normalization: lowercase, no extension, no separators, no leading batch number (`03_`), no ` (1)` copy suffix.
Matching: exact, or a known account name (≥5 chars) contained **inside** the file name (renamed-to-convention case).
Never the reverse direction — `brandx` inside `brandx_trunk` is a different creative.

## Commands

```
python scripts/creative_monitor.py                    # every project in rules/
python scripts/creative_monitor.py acme --all         # also list already-uploaded files
python scripts/creative_monitor.py acme --days 3      # only files touched in the last 3 days
python scripts/creative_monitor.py --telegram         # one message per project
```

Config: `rules/<project>.yaml` → `accounts`, `creatives.dir`, `creatives.include/exclude` (top-level folders),
`creatives.withdrawn` (names to treat as untested again). See `examples/rules/example.yaml`.

## Report

One message **per project** (so "launch this" is never ambiguous between projects):

```
AcmeApp · new creatives
7 not uploaded, 2 folder(s):
• Hooks_v2 — 5 video, today
• Statics — 2 image, 3 d ago
deploy: python scripts/launch_tests.py acme --folder <name>
```

Ages are by calendar day: "today / yesterday / N d ago".

## Honesty rules

- **Account not readable** (no access, 403): say so in the message — the list is then "everything in the folder",
  not "not uploaded". Never present an unchecked list as a checked one.
- **Drive busy** (cloud mount syncing): files are retried; anything still unreadable is counted and reported as incomplete.

## Schedule

Run daily before work starts (cron / Task Scheduler), e.g. `0 4 * * * cd ~/ops && python scripts/creative_monitor.py --telegram`.
Next step for a found batch → `creative-testing`.

## Blind spots

A renamed file looks new; a file uploaded under a different name is not detected.
