---
name: report
description: Generate daily Meta Ads performance reports. Use when the user types /report, asks for a report, daily stats, or performance overview. Triggers on "report", "daily report", "show stats", "performance".
---

# Daily Report

Generate Meta Ads performance reports with an account → campaign → adset breakdown (spend summary at every level).

## Commands

/report                    — all projects, yesterday
/report 7d                 — all projects, last 7 days
/report 30d                — all projects, last 30 days
/report <project>          — a single project: yesterday + 7d + 30d
/report <project> 7d       — a single project, last 7 days

`<project>` is the filename (without `.yaml`) of any config under `reports/`. See `examples/reports/example.yaml` and `examples/reports/subs-app.yaml` for two starter configs.

## Execution Steps

**Preferred path:** `python3 scripts/daily_report.py [project] [period] [--print]` implements this whole spec (including the Adjust ROAS/Predict lines for projects with `adjust: true`) and sends the result to Telegram; `--print` outputs to stdout instead. Use the manual MCP steps below only when the script isn't applicable.

### 1. Parse arguments

From the user's command, determine:
- **project**: any config name under `reports/`, or ALL (no argument)
- **period**: 7d, 30d, or default yesterday

If a specific project is given, generate 3 periods: yesterday, last_7d, last_30d.
If no project, generate one period only (yesterday by default, or 7d/30d if specified).

### 2. Read config(s)

Read YAML config(s) from reports/ directory in the project root:
- All projects: read every `reports/*.yaml` config
- Single project: read only reports/<project>.yaml

Each config carries a handful of report-shaping flags: `report_kind`, `adjust` (true/false), `show_applovin`, `roas_unavailable_note`, `show_leads_total`. These drive the formatting rules below — never hardcode a project name into the report logic.

### 3. Fetch data

For each account in each config, call mcp__meta-ads-mcp__get_insights:
- object_id: account id from config
- level: adset
- time_range: compute from period:
  - yesterday: {"since": "YYYY-MM-DD", "until": "YYYY-MM-DD"} where both dates = yesterday
  - 7d: {"since": "7 days ago", "until": "yesterday"}
  - 30d: {"since": "30 days ago", "until": "yesterday"}
- limit: 100

**Maximize parallel calls.** Call all accounts for the same period in parallel.

Count every API call. Report the total at the end.

**Projects with `adjust: true` — Adjust ROAS (every report, mandatory):** alongside Meta data, fetch per-campaign cohort metrics from the Adjust Report Service. Config: `reports/adjust.yaml` (api_url, tokens, app_tokens, m2_multiplier) — see `examples/reports/adjust.example.yaml`.

```
GET {api_url}?date_period=SINCE:UNTIL&app_token__in=<app_tokens, comma-joined>&dimensions=partner_name,campaign_network&metrics=cost,roas,roas_d3
Header: Authorization: Bearer <tokens[<project.token>]>
```

One request per period. Count Adjust requests separately and report them next to the Meta counter (`Meta API: X requests, Adjust API: Y`).

### 4. Extract metrics per adset

From each insight result, for each adset extract:
- adset_name from the result
- campaign_name from the result (used to group adsets under their campaign)
- spend from the result
- **conversions**: find the conversion count from actions array where action_type matches the conversion_action from config. Per-account conversion_action overrides project-level.
  - purchase → look for action_type purchase
  - lead → look for action_type lead
  - subscribe → look for action_type subscribe
- **revenue**: find value from action_values array where action_type matches the conversion_action. If not found, revenue = 0.
- **extra_metrics** (if config has extra_metrics): for each key/value pair, find the count from actions where action_type matches the value.

Compute, at each level (adset, campaign, account):
- CPA = spend / conversions (if conversions > 0, else "—")
- ROAS = revenue / spend * 100 (if spend > 0, else "—")
- For projects with `adjust: true`: installs from extra_metrics, CPI = spend / installs

**Projects with `adjust: true` — per-campaign Adjust ROAS + Predict M2:**
- Match Meta `campaign_name` ↔ Adjust `campaign_network`: full name, case-insensitive, trailing ` (digits)` stripped (display truncation to 8 chars is NOT used for matching)
- `Adjust ROAS` = roas × 100
- `Predict M2` = roas_d3 × 100 × `m2_multiplier[partner_name]` from reports/adjust.yaml (Facebook 2.01, Applovin 2.53 when `show_applovin` is true; unknown partner → Facebook)
- Skip the line when the campaign has no Adjust match or both roas and roas_d3 are 0
- Caveat: for the `yesterday` period the cohort is immature — roas_d3 hasn't accrued yet, so Predict M2 is understated; it matures by cohort day 3

**Skip adsets with $0 spend.** Group the remaining adsets by campaign_name, and campaigns under their account. Campaign and account subtotals are the sums of their children (spend, conversions, revenue, extra_metrics) — recompute CPA/ROAS/CPI from those sums, do not average the child rates.

### 5. Format output

Render as a **monospace aligned table** so columns line up, delivered inside a Telegram code block (triple backticks, `format: markdownv2`). Use the currency symbol from config ($ USD, € EUR).

**Mobile width is the hard constraint: keep every line ≤ 46 characters.** Telegram on phones wraps code-block lines past ~49 chars, which breaks the alignment. This caps the table at one name column + 3 numeric columns. Account/campaign/adset names that don't fit their column are truncated with `…`.

Layout — 3 levels per account: account header (totals), each campaign (`▸`, subtotals), then its adsets. Name in a fixed-width left column; numeric columns right-aligned under a per-project header row. Indentation inside the name column:
- account: no indent — `AccountName (…XXXX)`
- campaign: 2 spaces + `▸ Camp8chr` (campaign name trimmed to first 8 chars)
- adset: 6 spaces — `      adset_name`

Columns depend on the project's config flags (name-col width chosen so the widest row stays ≤ 46):
- Default `report_kind` (no `adjust`, no revenue tracked): name 24, then `spend(8)` + count `(4)` + `CPA(8)` = 44. Count header is `cv` (purchase) or `sub` (subscribe). If `roas_unavailable_note` is set, ROAS is omitted entirely (see below).
- Projects with `adjust: true`: name 24, then `spend(8)` + `inst(5)` + `CPI(8)` = 45 (installs from extra_metrics; no CPA/ROAS in the table). Under each campaign row add an Adjust line (6-space indent, ≤ 46 chars):
  ```
    ▸ Top10 Cr             €716.10 1714   €0.42
        Adjust ROAS 53%  Predict M2 97%
  ```
- Projects that track revenue (has revenue + ROAS): name 21, then `spend(8)` + `cv(4)` + `CPA(8)` + `ROAS(5)` = 46. If `show_leads_total` is true, the `lead` column is dropped to fit and account-level lead totals are printed on a note line under the account instead.
- When `roas_unavailable_note` is set and revenue is 0 for every row of an account, drop the ROAS column and add the one-line note from config, e.g. `(ROAS n/a — no purchase value via API)`.

**All-projects report (single period):** example showing the two widths.

```
Daily Report — DD.MM.YYYY
(account ▸ campaign ▸ adset)

=== AcmeApp (USD) ===
                           spend  cv     CPA
AccountName (…XXXX)      $XXX.XX  XX  $XX.XX
  ▸ Camp8chr             $XXX.XX  XX  $XX.XX
      adset_name          $XX.XX   X  $XX.XX
      adset_name          $XX.XX   0       —
AccountName2 (…XXXX): no active adsets
(ROAS n/a — no purchase value via API)

=== SubsApp (EUR) ===
                        spend  cv     CPA ROAS
AccountName (…XXXX)   €XXX.XX  XX  €XX.XX  XX%
  ▸ Camp8chr          €XXX.XX  XX  €XX.XX  XX%
      adset_name       €XX.XX   X  €XX.XX  XX%
(leads dropped for width — NN total)

Meta API: X requests
```

**Single-project report (3 periods):** same table, one block per period under `-- Yesterday (DD.MM.YYYY) --`, `-- Last 7 days --`, `-- Last 30 days --`.

**Formatting rules:**
- Sort campaigns by spend desc within each account; adsets by spend desc within each campaign
- Trim campaign names to the first 8 characters (collisions are acceptable — adset rows + spend disambiguate)
- Show last 4 digits of account ID in parentheses
- Right-align numeric columns; keep the name column a fixed width so everything lines up in monospace
- Round spend & CPA/CPI to 2 decimals, ROAS to whole percent; show `—` for CPA when conversions = 0, and `n/a` for ROAS when revenue is 0
- Conversion column header is `cv`; subscribe accounts use `sub`
- If an account has no data / no active adsets, show "no active adsets"; if account_status != 1, note "(inactive)"

### 6. Output

Deliver the report as a single Telegram message in a monospace code block (triple backticks, `format: markdownv2`) so columns stay aligned. If it exceeds Telegram's 4096-char limit, split into multiple code-block messages on account boundaries.
