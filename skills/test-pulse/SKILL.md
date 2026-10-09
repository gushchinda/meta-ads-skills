---
name: test-pulse
description: Use when the user asks for the test pulse / status of running creative tests, wants tests rotated automatically (slots, caps, queue), or asks "пульс тестов", "что с тестами", "test status", "rotate tests", "how many slots are free", "what launches next". Morning rotation of creative tests per project plus one HTML status page.
---

# Test pulse

The morning heartbeat of creative testing. Each project runs a fixed number of tests at once; every test has a spend
cap and a lifetime; finished tests free their slot; the next folder from the queue takes it. One HTML page shows it all.

## Model

| Term | Meaning |
|---|---|
| **slot** | one concurrent test. `rotation.max_slots` per project. ACTIVE adsets in `TEST…` campaigns that the rotation did not launch are **legacy**: they occupy slots and are never touched |
| **test** | one concept folder = one adset (via `creative-testing`), daily budget = `cap / test_days` |
| **cap** | lifetime spend per test: `rotation.test_cap`, or `ltv × cap_ltv_mult` |
| **queue** | folders with not-yet-uploaded creatives (`creative-monitor` check), **FIFO by first time seen**; `rotation.hold` waits |

## Every morning (`python scripts/pulse.py`)

1. **Reconcile** managed tests with Meta. Not ACTIVE any more → paused by someone else (usually `test-adset-stop`)
   → `EARLY_STOP`, slot freed, the stop rule's receipt attached. Never pause again, never resume.
2. **End** tests that reached the cap (`CAP`) or `test_days` (`AGE`) → pause, slot freed.
3. **Queue** rebuilt from the folders; folders already launched disappear from it by themselves.
4. **Free slots**: `rotation.enabled: true` → launch the oldest queued folders (one adset each, daily = cap/days).
   `enabled: false` → only say what is next in line. **Overflow** (more active tests than slots, because of manual or
   legacy adsets) → no launches, and nothing is stopped to make room.
5. **Report**: `run/test-pulse-<date>.html` + a short text per project (Telegram with `--telegram`).

```
python scripts/pulse.py --dry                           # reconcile + plan, change nothing
python scripts/pulse.py                                 # rotate + report
python scripts/pulse.py --lang ru --tz Asia/Novosibirsk # Russian page, local time next to UTC
python scripts/pulse.py --telegram --out public/        # put the page where you host reports
```

## The page, top to bottom

1. **Header**: date, Meta snapshot time, next pass (UTC + `--tz`).
2. **Deviations**: slot overflow, tests paused outside the rotation (with the stop-rule reason, e.g. `2 ≤ 3` leads),
   Meta errors on ads grouped by error code, launch/pause failures. Nothing to show = "no deviations".
3. **Project cards** side by side: icon, account time zone and currency, `active / max` slots with a segmented bar
   (overflow in red), slot status in words, new tests today, test limit `cap / 7 days`, check `daily × 7 = cap`,
   sum of daily budgets of all active TEST adsets, LTV. **Week · informational**: TEST spend vs guide, remaining
   limits of active tests, guide − spend − remaining, previous week; ready / HOLD folders. **30 full days**:
   videos in the folder, videos uploaded to Meta, creatives in finished tests (bars vs `monthly_target`), ads
   without impressions.
4. **Result of this pass** per project: launched yes/no, adset name and id, campaign, folder and count, limit and
   daily, geo with exclusions, end date, status read back from Meta; daily sum of active TEST before → after.
5. **Stops and replacements**: folder · id, reason, spend, age, which folder replaced it, stop-rule receipt.
6. **Active tests per project**: status, campaign, geo, daily, managed/unmanaged, age bar, spend/cap bar
   (unmanaged: "cap does not apply"), events (`conversion_event`, `lead_event`, `extra_events`), queue with
   QUEUED/HOLD and first-seen time, Meta issues.
7. **Queue-only projects** (`max_slots: 0`), then **sources and limits**.

Publish it where the team can open it (static hosting, an artifact, a shared drive) and send the link. The page is
self-contained, light/dark, mobile-friendly.

## Rules

- Turning `rotation.enabled` on means the script launches and pauses **by itself every morning** — get an explicit
  OK per project, run `--dry` first, and say the money: slots × daily = max test spend per day.
- **ACTIVE ≠ delivering.** A new adset is IN_PROCESS (review) for a while; don't claim impressions.
- **A finished test doesn't prove every creative got delivery** — report zero-delivery ads, don't call them losers.
- Order in the daily schedule: `adset_stop.py` → `pulse.py` → `budget_scaling.py`, so a test stopped by the rule
  frees its slot the same morning.
- A free slot with an empty queue is a request for new creatives — say it in the summary.

## Config (`rules/<project>.yaml`)

```yaml
ltv: 40
rotation:
  enabled: false
  max_slots: 5
  test_days: 7
  test_cap: null        # null = ltv × cap_ltv_mult
  cap_ltv_mult: 5
  weekly_guide: 700
  hold: []
  geo: null             # [US, GB, AU] to override the template adset's countries
  monthly_target: 125   # optional: creatives per 30 days, shown as bars
  extra_events: [complete_registration]
icon: https://example.com/icon.png   # optional, shown on the project card
```

Needs the `testing:` section as well (campaign, template adset, page, link) — launches go through `creative-testing`.
State: `run/pulse-<project>.json` (tests + queue).
