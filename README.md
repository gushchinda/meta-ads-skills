# meta-ads-skills

Claude Code skills for Meta Ads user-acquisition — daily reporting, ROAS prediction, creative generation, and creative deployment.

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

## Setup

1. Copy `.env.example` → `.env` and fill in the keys you need (see Integrations below).
2. Copy the project configs you want — `examples/reports/example.yaml`, `examples/reports/subs-app.yaml` — into `reports/`, one file per project you want to report on. Don't blanket-copy `examples/reports/*.yaml`: `adjust.example.yaml` isn't a project config. If you set `adjust: true` on a project, separately copy `examples/reports/adjust.example.yaml` → `reports/adjust.yaml` (the report script expects it at that exact path) and fill in `ADJUST_API_TOKEN`.
3. Copy `examples/clients/example.yaml` → `clients/` and edit it with your real ad account ID, page/pixel IDs, targeting, and destination — this drives the `deploy-creatives` skill.

## Integrations

Every integration below is optional — each skill degrades gracefully or simply doesn't apply if the corresponding key is missing.

- **Meta Graph API** — used by `report` and `deploy-creatives`. Supply either a Pipeboard token (`PIPEBOARD_API_TOKEN`) or a raw Meta access token (`META_ACCESS_TOKEN`).
- **Google Gemini (Nano Banana)** — used by `generate-creatives` for image generation. Set `GEMINI_API_KEY` (get one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)).
- **Adjust Report Service** — used by `report` and `predict` for cohort/Adjust ROAS lines when a project config sets `adjust: true`. Set `ADJUST_API_TOKEN`.
- **Telegram** — used by `report` to deliver the daily report to a chat. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

## Scripts

```
python scripts/daily_report.py <project> [yesterday|7d|30d|YYYY-MM-DD] [--print]
python scripts/gen_nano_banana.py --prompts <path>
```

Omit `<project>` in `daily_report.py` to report on every config under `reports/`. `--print` writes to stdout instead of sending to Telegram.

## Disclaimer

Everything under `examples/` is placeholder data — account IDs, tokens, and app names are all fictional. Replace them with your own before running any skill or script. No real account IDs, tokens, or client data are included in this repository.

## License

MIT — see [LICENSE](LICENSE).
