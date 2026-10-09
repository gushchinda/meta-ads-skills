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
   → `EARLY_STOP`, slot freed. Never pause again, never resume.
2. **End** tests that reached the cap (`CAP`) or `test_days` (`AGE`) → pause, slot freed.
3. **Queue** rebuilt from the folders; folders already launched disappear from it by themselves.
4. **Free slots**: `rotation.enabled: true` → launch the oldest queued folders (one adset each, daily = cap/days).
   `enabled: false` → only say what is next in line.
5. **Report**: `run/test-pulse-<date>.html` + a short text per project (Telegram with `--telegram`).

```
python scripts/pulse.py --dry                 # reconcile + plan, change nothing
python scripts/pulse.py                       # rotate + report
python scripts/pulse.py acme --telegram --out public/   # put the page where you host reports
```

## Short summary (one per project)

```
AcmeApp · test pulse · slots 5/5 · cap $200.00 / 7 d = $28.57/day
⏹ Hooks_v2 — EARLY_STOP · $96.10, 0 purchase
⏹ Pain — CAP · $201.40, 3 purchase
▶️ launched Statics_10 (6 creatives) → 1202…
queue: 2 folder(s) / 15 creatives · week TEST spend $412.00 / $700.00
```

## HTML page

Per project card: slots `active / max`, LTV and cap, week TEST spend vs `weekly_guide` and the remaining caps of running
tests (informational, never blocks a launch), ended / launched / next-in-line list, a tile per running test with
**age bar (d / 7)** and **spend bar ($ / cap)**, purchases and leads, **zero-delivery ads** count, legacy tiles, queue.

Publish it where the team can open it (static hosting, an artifact, a shared drive) and send the link — the page is
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
```

Needs the `testing:` section as well (campaign, template adset, page, link) — launches go through `creative-testing`.
State: `run/pulse-<project>.json` (tests + queue).
