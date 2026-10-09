# meta-ads-skills

Claude Code skills for Meta Ads user-acquisition — daily reporting, ROAS prediction, creative generation and deployment, plus a daily ops loop: new-creative monitoring, creative testing, statistical stop / early stop of test adsets, and ROAS-based budget scaling.

## Install

```
/plugin marketplace add gushchinda/meta-ads-skills
/plugin install meta-ads-skills
```

## Skills

| Skill | What it does | Example |
|---|---|---|
| `report` | Generate daily Meta Ads performance reports (account → campaign → adset breakdown). | `/report` or `/report AcmeApp 7d` |
| `predict` | Build ROAS predictions from stored cohort revenue curves and fresh weekly data. | `/predict AcmeApp` |
| `generate-creatives` | Generate Meta-ready ad creative images with Google Nano Banana (`gemini-2.5-flash-image`), enforcing Meta sizing and a mandatory text-verification pass. | `/generate-creatives AcmeApp launch` |
| `deploy-creatives` | Deploy video/image creatives from a folder into a Meta Ads test campaign. | `deploy launch for AcmeApp` |
| `creative-monitor` | Scan a project's creative folder against the ad account and list what is not launched yet — one message per project. | `what new creatives do we have?` |
| `creative-testing` | Launch new creatives into the `TEST…` campaign: one concept folder = one adset cloned from a template adset; resumable, no duplicates. | `launch Hooks_v2 into tests for AcmeApp` |
| `test-adset-stop` | Stop and early-stop losing test adsets with a Poisson rule derived from LTV: early stop on leads, daily stop on purchases. | `run the autostop` / `why was this adset stopped?` |
| `budget-scaling` | Daily ±15% budget moves on Predicted ROAS for `SCALING…` campaigns (CBO or per-adset ABO), one move per day, floor/ceiling. | `scale budgets` |

### Daily ops loop

Campaign names carry the role: `TEST…` campaigns receive new concepts and are policed by `test-adset-stop`;
`SCALING…` campaigns hold proven creatives and are moved by `budget-scaling`. One config per project in
`rules/<project>.yaml` (copy `examples/rules/example.yaml`). Suggested schedule:

```
python scripts/creative_monitor.py --telegram   # what's new in the folders
python scripts/adset_stop.py --telegram         # pause losing test adsets first
python scripts/budget_scaling.py --telegram     # then move scaling budgets
python scripts/launch_tests.py <project> --dry  # on demand: launch a new batch into tests
```

Every money-moving script has `--dry`. Run it first and get an explicit OK before scheduling the real run.

## Setup

1. Copy `.env.example` → `.env` and fill in the keys you need (see Integrations below).
2. Copy the project configs you want — `examples/reports/example.yaml`, `examples/reports/subs-app.yaml` — into `reports/`, one file per project you want to report on. Don't blanket-copy `examples/reports/*.yaml`: `adjust.example.yaml` isn't a project config. If you set `adjust: true` on a project, separately copy `examples/reports/adjust.example.yaml` → `reports/adjust.yaml` (the report script expects it at that exact path) and fill in `ADJUST_API_TOKEN`.
3. Copy `examples/clients/example.yaml` → `clients/` and edit it with your real ad account ID, page/pixel IDs, targeting, and destination — this drives the `deploy-creatives` skill.
4. For the ops-loop skills, copy `examples/rules/example.yaml` → `rules/<project>.yaml` and fill in accounts, LTV, creative folder and the TEST campaign / template adset. `rules/` and `run/` (state, stop journal) are git-ignored.

## Integrations

Every integration below is optional — each skill degrades gracefully or simply doesn't apply if the corresponding key is missing.

- **Meta Graph API** — used by `report`, `deploy-creatives` and the four ops-loop skills (needs `ads_management` to pause and change budgets). Supply either a Pipeboard token (`PIPEBOARD_API_TOKEN`) or a raw Meta access token (`META_ACCESS_TOKEN`).
- **Google Gemini (Nano Banana)** — used by `generate-creatives` for image generation. Set `GEMINI_API_KEY` (get one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)).
- **Adjust Report Service** — used by `report` and `predict` for cohort/Adjust ROAS lines when a project config sets `adjust: true`. Set `ADJUST_API_TOKEN`.
- **Telegram** — used by `report` and by the ops-loop scripts with `--telegram` (without the keys they print to stdout). Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

## Scripts

```
python scripts/daily_report.py <project> [yesterday|7d|30d|YYYY-MM-DD] [--print]
python scripts/gen_nano_banana.py --prompts <path>
python scripts/creative_monitor.py [project ...] [--days N] [--all] [--telegram]
python scripts/launch_tests.py <project> [--folder NAME ...] [--as NAME] [--geo US,GB] [--link URL] [--paused] [--dry]
python scripts/adset_stop.py [project ...] [--dry] [--telegram] | --describe <project>
python scripts/budget_scaling.py [project ...] [--dry] [--force] [--telegram]
```

Omit `<project>` in `daily_report.py` to report on every config under `reports/`. `--print` writes to stdout instead of sending to Telegram.

## Disclaimer

Everything under `examples/` is placeholder data — account IDs, tokens, and app names are all fictional. Replace them with your own before running any skill or script. No real account IDs, tokens, or client data are included in this repository.

## License

MIT — see [LICENSE](LICENSE).
