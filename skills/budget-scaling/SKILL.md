---
name: budget-scaling
description: Use when the user asks to scale budgets by ROAS, set up a daily scaling rule, or asks why a budget moved — "scaling", "скейлинг", "подними бюджет если ROAS > 100%", "scale winners", "±15% rule". Daily ±step budget moves on Predicted ROAS for campaigns named SCALING…, one move per object per day.
---

# Budget scaling

Daily budget rule for **campaigns named `SCALING…`** (rename a campaign to put it under the rule).

```
Predicted ROAS = conversions × LTV × roas_multiplier / spend      over the window
window         = window_days (7) ending lag_days ago (1 = yesterday)
ROAS >  pivot (100%) → budget × (1 + step_up)    +15%
ROAS ≤  pivot        → budget × (1 − step_down)  −15%, clamped to [min_budget, max_budget]
```

- **CBO** (budget on the campaign) → one move by the campaign's ROAS.
- **ABO** (budgets on adsets) → **each ACTIVE adset by its own ROAS**; a strong adset must not drag a weak one up.
- No spend in the window → not touched (no number to decide on).

## Commands

```
python scripts/budget_scaling.py --dry           # preview every move
python scripts/budget_scaling.py                 # apply
python scripts/budget_scaling.py acme --telegram
python scripts/budget_scaling.py acme --force    # move again today (deliberate override, printed in the report)
```

## Report (one message per project, ROAS on the same line as the money)

```
AcmeApp · scaling · window 02.10–08.10
SCALING. Winners – US
  $1,240.00 · 41 purchase × $40.00
  📈 campaign (CBO) · ROAS 132% > 100% · $150.00 → $172.50
SCALING. Statics – T1
  📉 03. Pain ($310.00, 6 purchase) · ROAS 77% ≤ 100% · $60.00 → $51.00
```

## Rules

- **One move per object per day.** Every move is saved to `run/scaling-applied.json` with before/after. Re-runs the
  same day do nothing. If the live budget differs from the recorded `after`, **someone else changed it** — report it,
  don't stack a move on top.
- **Same window as the numbers the user sees.** If the daily report/banner uses another window, align them;
  otherwise money moves on numbers nobody saw.
- **Maturity:** if conversions keep arriving for days (app cohorts, trials), set `lag_days` to the maturation lag
  (e.g. 4) so fresh, under-counted days don't read as losses. If conversions are final next day, `lag_days: 1`.
- **Compounding:** +15%/day ≈ ×2.7 per week. Always set `max_budget`; hitting it is a signal to ask for a new ceiling,
  not a bug. `min_budget` keeps repeated −15% from shrinking to nothing.
- `roas_multiplier` (if not 1) is printed in the formula line — never hide a correction inside the result.
- Budget changes move real money: `--dry` and an explicit OK before the first scheduled run for a project.
- Run **after** `test-adset-stop` in the daily schedule.

## Config (`rules/<project>.yaml`)

```yaml
ltv: 40
conversion_event: purchase
roas_multiplier: 1.0
scaling: {campaign_prefix: SCALING, window_days: 7, lag_days: 1, pivot: 1.0,
          step_up: 0.15, step_down: 0.15, min_budget: 5, max_budget: 500}
```

## Daily schedule (all four skills)

```
04:00  creative_monitor.py --telegram   # what's new
04:10  adset_stop.py --telegram         # pause losers first
04:20  budget_scaling.py --telegram     # then move budgets
```
