#!/usr/bin/env python3
"""Daily budget scaling on Predicted ROAS — at most one move per object per day.

    python scripts/budget_scaling.py [project ...] [--dry] [--force] [--telegram]

Scope: ACTIVE campaigns whose name starts with `scaling.campaign_prefix`
(default SCALING). Renaming a campaign is how you put it under (or out of)
the rule — an id list goes stale silently, a prefix is visible in Ads Manager.

    Predicted ROAS = conversions × LTV × roas_multiplier / spend
    window         = `window_days` ending `lag_days` ago (lag 1 = up to yesterday;
                     use the cohort maturation lag if late conversions still arrive)
    ROAS > pivot   → budget × (1 + step_up)
    ROAS ≤ pivot   → budget × (1 − step_down), clamped to [min_budget, max_budget]

CBO campaign → one move on the campaign budget by the campaign's ROAS.
ABO campaign → each ACTIVE adset moved by ITS OWN ROAS (a strong adset must not
drag a weak one up, or the other way round). An adset without spend in the
window is not moved — there is no number to decide on.

One move per day: every move is recorded in run/scaling-applied.json with
before/after. A second run the same day does nothing; if the current budget
differs from the recorded `after`, someone else changed it and the script says
so instead of stacking a move on top. `--force` overrides deliberately.
Budgets compound (+15%/day ≈ ×2.7 per week), so set max_budget.
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ua_rules import common  # noqa: E402

STATE = "scaling-applied.json"


def window(cfg, today=None):
    today = today or date.today()
    until = today - timedelta(days=cfg["lag_days"])
    return until - timedelta(days=cfg["window_days"] - 1), until


def predicted_roas(spend, conversions, ltv, mult=1.0):
    return conversions * ltv * mult / spend if spend > 0 else None


def new_budget(cur, up, cfg):
    """cur and result in MAJOR units (dollars), clamped to [min_budget, max_budget]."""
    k = 1 + cfg["step_up"] if up else 1 - cfg["step_down"]
    new = round(cur * k, 2)
    if cfg.get("min_budget") is not None:
        new = max(new, float(cfg["min_budget"]))
    if cfg.get("max_budget") is not None:
        new = min(new, float(cfg["max_budget"]))
    return new


def guard(state, obj_id, cur_cents, today=None):
    """Refusal text if I already moved this object today, else None."""
    rec = state.get(obj_id)
    if not rec or rec.get("date") != (today or date.today()).isoformat():
        return None
    head = f"already moved today {rec['before'] / 100:.2f} → {rec['after'] / 100:.2f}"
    if int(cur_cents) != int(rec["after"]):
        return head + f"; now {int(cur_cents) / 100:.2f} — someone else changed it, not touching"
    return head + " — no second move per day"


def run_project(pj, dry, force, state, today=None):
    cfg = pj["scaling"]
    if not cfg["enabled"]:
        return None
    if pj["ltv"] is None:
        return f"<b>{pj['name']}</b> · scaling: ltv not set — nothing done"
    since, until = window(cfg, today)
    tr = json.dumps({"since": since.isoformat(), "until": until.isoformat()})
    ev, mult, pivot = pj["conversion_event"], float(pj["roas_multiplier"] or 1), cfg["pivot"]
    m = lambda v: common.money(pj, v)  # noqa: E731
    lines = []

    def move(obj_id, label, cur_cents, roas):
        up = roas > pivot
        blocked = None if force else guard(state, obj_id, cur_cents, today)
        if blocked:
            lines.append(f"  {label} — {blocked}")
            return
        cur = cur_cents / 100
        new = new_budget(cur, up, cfg)
        arrow = "📈" if up else "📉"
        if abs(new - cur) < 0.005:
            lines.append(f"  {arrow} {label} · ROAS {roas:.0%} · {m(cur)} at {'ceiling' if up else 'floor'}, no change")
            return
        if not dry:
            r = common.post(obj_id, {"daily_budget": str(int(round(new * 100)))})
            if "error" in r:
                lines.append(f"  {label}: FAILED {str(r['error'])[:80]}")
                return
            state[obj_id] = {"date": (today or date.today()).isoformat(),
                             "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "name": label, "before": int(cur_cents), "after": int(round(new * 100)),
                             "roas": round(roas, 4)}
            common.save_state(STATE, state)
        lines.append(f"  {arrow} {label} · ROAS {roas:.0%} {'>' if up else '≤'} {pivot:.0%} · "
                     f"{m(cur)} → <b>{m(new)}</b>{' (dry)' if dry else ''}{' (--force)' if force else ''}")

    n = 0
    for acct in pj["accounts"]:
        camps = [c for c in common.get(f"{acct}/campaigns", fields="id,name,effective_status,daily_budget", limit=200)
                 if c["effective_status"] == "ACTIVE" and common.has_prefix(c["name"], cfg["campaign_prefix"])
                 and common.matches(pj, c["name"])]
        for c in camps:
            n += 1
            lines.append(f"<b>{c['name']}</b>")
            cb = float(c.get("daily_budget") or 0)
            if cb > 0:
                rows = common.get(f"{c['id']}/insights", level="campaign", time_range=tr,
                                  fields="spend,actions,conversions", limit=50)
                spend = sum(float(x["spend"]) for x in rows)
                conv = sum(common.act_val(x, ev) for x in rows)
                roas = predicted_roas(spend, conv, pj["ltv"], mult)
                if roas is None:
                    lines.append("  no spend in window — not touching")
                    continue
                lines.append(f"  {m(spend)} · {conv} {ev} × {m(pj['ltv'])}{f' × {mult:g}' if mult != 1 else ''}")
                move(c["id"], "campaign (CBO)", cb, roas)
                continue
            rows = common.get(f"{c['id']}/insights", level="adset", time_range=tr,
                              fields="adset_id,spend,actions,conversions", limit=200)
            per = {x["adset_id"]: (float(x["spend"]), common.act_val(x, ev)) for x in rows}
            for s in common.get(f"{c['id']}/adsets", fields="id,name,effective_status,daily_budget", limit=200):
                sb = float(s.get("daily_budget") or 0)
                if s["effective_status"] != "ACTIVE" or sb <= 0:
                    continue
                spend, conv = per.get(s["id"], (0.0, 0))
                roas = predicted_roas(spend, conv, pj["ltv"], mult)
                if roas is None:
                    lines.append(f"  {s['name'][:40]} — no spend in window, not touching")
                    continue
                move(s["id"], f"{s['name'][:40]} ({m(spend)}, {conv} {ev})", sb, roas)
    if not n:
        lines.append(f"no ACTIVE campaigns named '{cfg['campaign_prefix']}*'")
    head = f"<b>{pj['name']}</b> · scaling · window {since:%d.%m}–{until:%d.%m}"
    return head + "\n" + "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="*")
    ap.add_argument("--dry", action="store_true", help="preview, change nothing, write no state")
    ap.add_argument("--force", action="store_true", help="move even if already moved today")
    ap.add_argument("--telegram", action="store_true")
    a = ap.parse_args()
    state = common.load_state(STATE)
    for pj in common.load_projects(a.projects):
        text = run_project(pj, a.dry, a.force, state)
        if text:
            common.send(text) if a.telegram else print(text.replace("<b>", "").replace("</b>", ""), "\n")


if __name__ == "__main__":
    main()
