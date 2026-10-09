---
name: creative-testing
description: Use when the user wants new creatives launched into a test campaign — "launch tests", "залей новые креативы в тест", "put folder X into the test campaign", "test these concepts", or right after creative-monitor found new batches. One concept folder = one new adset in the TEST campaign, settings cloned from a template adset.
---

# Creative testing

Launches new creatives into the project's **TEST campaign**: one concept = one adset, everything else identical,
so the campaign is a clean comparison of concepts.

## Campaign naming convention (shared with test-adset-stop and budget-scaling)

| Prefix | Meaning | Rule that acts on it |
|---|---|---|
| `TEST…` | new adsets land here, each concept gets its own adset | `test-adset-stop` pauses losers |
| `SCALING…` | proven creatives, budget follows ROAS | `budget-scaling` ±15%/day |

Moving a campaign between roles = renaming it. No id lists to go stale.

## What the launcher does

```
python scripts/launch_tests.py acme --dry                       # plan: what, how many adsets, +$/day
python scripts/launch_tests.py acme                             # every not-uploaded file, grouped by parent folder
python scripts/launch_tests.py acme --folder Hooks_v2 --folder Pain
python scripts/launch_tests.py acme --folder A --folder B --as AB_mix   # merge into ONE adset (explicit only)
python scripts/launch_tests.py acme --folder UK_hooks --geo GB,IE       # override countries only
python scripts/launch_tests.py acme --folder Promo --link https://example.com/promo-funnel
python scripts/launch_tests.py acme --paused                            # create everything PAUSED
```

1. Finds not-uploaded files with the same check as `creative-monitor`. Refuses to run if the account can't be read.
2. Creates adset `NN. <concept>` in `testing.campaign_id` (numbering continues the campaign's), `testing.daily_budget`,
   with targeting / optimization / bid / attribution / promoted object **copied from `testing.template_adset_id`**.
3. Per file: upload → video: wait for `ready`, take the preferred thumbnail (required, Graph subcode 1443226) → creative → ad.
   **Ad name = file name without extension.** Images are supported too (single-image link ad).
4. Journal `run/deploy-<project>.json` → an interrupted run resumes without duplicates; a lock file blocks a parallel run.

## Rules

- **Always show `--dry` first** unless the user has given a standing "launch without asking" for this project.
  State the added spend: `+$X/day` (budget × new adsets). `testing.status: ACTIVE` means money starts flowing immediately.
- **One concept per adset by default.** Merging (`--as`) loses the answer "which batch worked" — Meta converges on 1–2 ads; say so.
- **Geo override replaces only the country list**; all other targeting stays from the template (adsets must stay comparable).
- **Destination link is frozen into the creative** — creatives are immutable, a wrong funnel means recreating the ad and losing learning.
  If a batch belongs to a different funnel, pass `--link` explicitly; don't guess from a folder name.
- **Texts:** empty `title`/`message` are not sent at all — a text on one adset and none on the others is a second variable.
- **UTM / url_tags go on the creative** (`testing.url_tags`); the ad object silently drops them.
- After the launch, report: adsets created (name → id), ads created, budget added per day, anything that failed and why.

## Config

`rules/<project>.yaml` → `accounts`, `creatives.dir`, `testing.*` (campaign_id, template_adset_id, daily_budget, status,
page_id, instagram_user_id, link, cta, title, message, url_tags). See `examples/rules/example.yaml`.
