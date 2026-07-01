---
name: predict
description: Build ROAS predictions from cohort data. Use when the user types /predict, asks for ROAS prediction, revenue forecast, or wants to set up cohort data for an app.
---

# ROAS Prediction

Predict future ROAS based on stored cohort revenue curves and fresh weekly data.

## Commands

```
/predict                        — show instructions + list of configured apps
/predict setup [app] [path]     — store cohort file for an app
/predict [app]                  — build prediction (asks for fresh CSV)
```

## App Configuration

Each app has a config stored in `cohorts/` directory in the project root.

### Config files

`cohorts/<app>.yaml` — created by `/predict setup`, contains:

```yaml
name: AcmeApp
platform: adapty          # adapty or adjust
has_trials: true
cohort_file: acmeapp_cohorts.csv
uploaded: 2026-06-06
fields:
  - campaign_name
  - date_day
  - spend
  - installs
  - total_revenue
  - count_trial_started
  - count_trial_converted
```

### Known apps

| App | Platform | Trials | Key fields |
|-----|----------|--------|------------|
| AcmeApp | Adapty | yes | campaign_name, date_day, spend, installs, total_revenue, count_trial_started, count_trial_converted |
| SubsApp | Adjust | yes | campaign_network, cost, installs, all_revenue_total_d0, count_trial_started, count_trial_converted |
| GameApp | Adjust | no | campaign_network, cost, installs, all_revenue_total_d0, all_revenue_total_m3 |

## /predict (no args) — Show Instructions

Output this text:

```
ROAS Prediction

Configured apps:
  [list from cohorts/*.yaml with name, platform, upload date]
  (if none: "No apps configured. Run /predict setup [app] [path] first.")

To build a prediction:
1. Download CSV from Adapty/Adjust for the last week
   Required fields for [app]:
   [list fields from app config]
2. Run: /predict [app]
3. Paste the file path

To update cohorts: /predict setup [app] [path]
```

When listing configured apps, read all `cohorts/*.yaml` files.

## /predict setup [app] [path]

1. Read the CSV file at [path]
2. Auto-detect format:
   - Has `cohort, start_value, 3d, 7d, 14d, 28d` → Adapty Cohorts
   - Has `cost, installs, all_revenue_total_d0` → Adjust
3. Detect if app has trials (check for `count_trial_started` or similar column)
4. Determine required fields based on platform + trials
5. Copy CSV to `cohorts/[app]_cohorts.csv`
6. Create/update `cohorts/[app].yaml` with config
7. Confirm:

```
Saved cohort data for [App Name]
Platform: Adapty/Adjust
Trials: yes/no
Cohort rows: N
Date range: DD.MM.YYYY - DD.MM.YYYY
```

## /predict [app]

### Step 1: Show required fields

Read `cohorts/[app].yaml` and output:

```
[App Name] — ROAS Prediction

Download CSV from [Adapty/Adjust] for the target period.
Required fields:
  [field1], [field2], [field3], ...

Paste the file path:
```

### Step 2: Parse fresh CSV

Read the CSV file. Extract per-campaign or aggregate:
- **spend**: total spend in the period
- **installs**: total installs
- **revenue**: early revenue (d0 or total_revenue depending on platform)
- **trials** (if has_trials): count_trial_started, count_trial_converted
- **date range**: from date columns or filename

### Step 3: Build prediction

1. Load the stored cohort curve. **If the app config has a `channel_cohorts` map, pick the curve whose channel matches the fresh data's `channel` column** (e.g. Applovin data → `gameapp_applovin_cohorts.csv`); otherwise fall back to `cohort_file` / `cohorts/[app]_cohorts.csv`. Cohort curves are channel-specific — don't predict AppLovin data off a Facebook curve. When building the curve, use only rows with cost > 0 and non-zero d0 & m2, and aggregate revenue-weighted (Σ roas·cost ÷ Σ cost).

   **⚠ Cohort maturity (carry-forward trap) — drop immature points before fitting.** Adjust/Adapty return `dN` as carry-forward (current value) when the cohort is younger than N days, so a fresh cohort shows fake-flat d7≈d14≈d30. Fitting a curve through carry-forward points produces garbage. For any cohort window ending on date `U` with last complete day `T`, only days `N ≤ T − U` are real; **drop every dN with N > T − U** from the fit (don't fit, don't extrapolate from them). To get a trustworthy point at day N, the cohort window must end ≥ N+1 days before today (Meta-lag: ≥ N+2). When the freshest available point is shallow (only d0/d3 mature), extrapolate from a STORED mature curve's shape — never from the immature tail.
2. Extract revenue multipliers from cohort data:
   - For Adapty: use `3d, 7d, 14d, 28d` columns relative to `start_value`
   - For Adjust: use `roas_d0, roas_d3, roas_m2, roas` (m3) to build curve
3. Fit a power law curve to the revenue progression points
4. Extrapolate to 2 months (60 days)
5. Apply the growth multiplier to the fresh weekly revenue to get predicted revenue
6. Compute: Predicted ROAS = predicted_revenue / spend * 100

### Step 4: Output

```
[Project Name]
[DD.MM.YYYY - DD.MM.YYYY]
Predicted ROAS (2 month): XX%

  $X,XXX  CPA $XX  ROAS(2m) XX%  Name 1
  $X,XXX  CPA $XX  ROAS(2m) XX%  Name 2

  $X,XXX  CPA $XX  ROAS(2m) XX%  TOTAL
```

- Total predicted ROAS appears right after the date range
- Breakdown sorted by spend descending, then total line
- Numbers right-aligned for readability
- CPA = spend / installs (if installs > 0, else "—"). Omit CPA if `show_cpa: false` in app config
- Breakdown level: use `breakdown` field from app config — `adset` (use adgroup_network) or `campaign` (use campaign_network). Default: campaign
- Use currency from the client config if available, default USD
- Round spend and CPA to whole dollars, ROAS to whole percent

### Prediction math

**Power law model**: Revenue(t) = a * t^b

Given cohort data points (day, cumulative_revenue):
- Adapty: (3, rev_3d), (7, rev_7d), (14, rev_14d), (28, rev_28d)
- Adjust: (0, rev_d0), (3, rev_d3), (60, rev_m2), (90, rev_m3)

1. Fit log-log linear regression: log(revenue) = log(a) + b * log(day)
2. Predict revenue at day 60: Revenue(60) = a * 60^b
3. Growth multiplier = Revenue(60) / Revenue(latest_known_day)
4. Predicted revenue = fresh_revenue * growth_multiplier
5. Predicted ROAS = predicted_revenue / spend * 100%

If the fresh CSV has revenue at an early stage (e.g., d0 or d7), use the cohort curve to project what that revenue will grow to by day 60.
