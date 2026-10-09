---
name: test-adset-stop
description: Use when the user asks to stop or early-stop losing test adsets, set up an auto-stop / kill rule, explain why an adset was paused, or show the stop thresholds — "автостоп", "ранний стоп", "kill rule", "stop losing adsets", "when will this adset be stopped", "правило выключения". Statistical (Poisson) rule on lifetime spend vs. leads and purchases, derived from LTV.
---

# Test adset stop & early stop

Pauses test adsets that have spent enough to prove they won't pay back. Everything is derived from **one number — LTV
of a paying user** — plus a tolerated error `alpha`. Scope: ACTIVE adsets in ACTIVE campaigns named `TEST…`.
Spend and events are **lifetime** (has this test had enough money in total).

## The rule

```
CPA    = LTV / roas_target              break-even cost per purchase
S_min  = min_spend_cpa_mult × CPA       below this an adset is never touched
S_lead = max(lead_spend_threshold, S_min)
```

**1. Early stop — leads, checked once.** When spend first reaches `S_lead`, count the upper-funnel event
(`lead_event`: install / registration / trial). A break-even adset should show at least
`mu = S_lead / (LTV × p_max)` of them (`p_max` = the most optimistic lead→purchase rate).
Kill if `leads ≤ n*`, the largest n with `P(Poisson(mu) ≤ n) < alpha`.
If even 0 leads isn't rare enough (`P(0) ≥ alpha`) the check has no power and never fires — the script says so.

**2. Stop — purchases, checked daily.** With `n` purchases so far, kill when
`spend > max(k(n) × CPA, S_min)`, where `P(Poisson(k) ≤ n) = alpha`.
With alpha 5%: 0 purchases → ~3.0×CPA, 1 → ~4.7×CPA, 2 → ~6.3×CPA …

Example (LTV $40, alpha 5%, p_max 20%):

```
python scripts/adset_stop.py --describe acme
AcmeApp · stop rule · campaigns 'TEST*'
LTV $40.00 | CPA $40.00 | alpha 5% | p_max 20%
S_min $80.00 — never touched below
early stop: once at spend ≥ $100.00, kill if mobile_app_install ≤ 6 (healthy ≥ 12.5)
stop: kill when lifetime spend exceeds
  0 purchase(s): $119.83
  1 purchase(s): $189.75
  2 purchase(s): $251.83
```

Always show this table when a user sets up or questions the rule — it turns "why was it stopped" into arithmetic.

## Commands

```
python scripts/adset_stop.py --dry            # what would be paused, nothing changes
python scripts/adset_stop.py                  # pause + journal
python scripts/adset_stop.py acme --telegram  # one report per project
python scripts/adset_stop.py --describe acme  # thresholds table
```

## Rules

- **Only pauses** the adset (never the campaign, never deletes, never touches budgets). Neighbours in the campaign keep running.
- The pause must be confirmed (`success: true`); a failed pause is reported as FAILED, not as stopped.
- Every stop goes to `run/autostop.csv` (date, campaign, adset, spend, purchases, LTV, reason) — use it to check
  whether the rule kills eventual winners before tightening `alpha`.
- Early-stop result is stored per adset in `run/stop-rule.json`; it runs once.
- No `ltv` in the config → report "LTV not set" and do nothing. Never invent an LTV.
- Pausing spend is a money decision: run `--dry` first the first time for a project and get an explicit OK
  before scheduling the real run.
- Run it **before** `budget-scaling` in the daily schedule, so scaling never raises a budget on an adset stopped today.

## Config (`rules/<project>.yaml`)

```yaml
ltv: 40
conversion_event: purchase
lead_event: mobile_app_install      # or lead / complete_registration / start_trial
stop_rule: {campaign_prefix: TEST, alpha: 0.05, p_max: 0.20, roas_target: 1.0,
            min_spend_cpa_mult: 2, lead_spend_threshold: 100}
```

Tuning: higher `alpha` stops sooner (more false kills); higher `p_max` makes the early stop more lenient.
