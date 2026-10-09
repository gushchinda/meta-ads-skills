#!/usr/bin/env python3
"""Stop and early-stop of test adsets — a cumulative Poisson rule.

    python scripts/adset_stop.py [project ...] [--dry] [--telegram]
    python scripts/adset_stop.py --describe <project>     # print the thresholds table

Applies to ACTIVE adsets in ACTIVE campaigns whose name starts with
`stop_rule.campaign_prefix` (default TEST). Spend and events are LIFETIME
(date_preset=maximum): "has this test had enough money" is about the total.

Definitions (all money in account currency):
    CPA     = LTV / roas_target          the break-even cost per purchase
    S_min   = min_spend_cpa_mult × CPA   below this an adset is never touched
    S_lead  = max(lead_spend_threshold, S_min)

1. EARLY STOP (lead test, once per adset). When spend first reaches S_lead,
   count the upper-funnel event (`lead_event`: install, registration, trial…).
   A healthy adset would show at least mu = S_lead / (LTV × p_max) leads,
   p_max being the most optimistic lead→purchase rate you believe in.
   Kill if leads ≤ n*, the largest n with P(Poisson(mu) ≤ n) < alpha.
   If even 0 leads is not unlikely enough (P(0) ≥ alpha) the test has no power
   and never fires.

2. STOP (purchase test, daily). With n purchases so far, kill when
   spend > max(k(n) × CPA, S_min), where k(n) solves P(Poisson(k) ≤ n) = alpha:
   the spend at which seeing only n purchases from a break-even adset is an
   alpha-rare event. 0 purchases → stop at ~3×CPA (alpha 5%), 1 → ~4.7×CPA, …

The rule only pauses (never deletes, never touches budgets). Every stop is
journaled to run/autostop.csv with its economics, so "does the rule kill the
winners?" can be answered from data later.
"""
import argparse
import csv
import math
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ua_rules import common  # noqa: E402

STATE = "stop-rule.json"
JOURNAL = "autostop.csv"


def pcdf(n, mu):
    """Poisson CDF P(X ≤ n), computed in log space (stable for large mu)."""
    if n < 0:
        return 0.0
    if mu == 0:
        return 1.0
    logs = [-mu + j * math.log(mu) - math.lgamma(j + 1) for j in range(int(n) + 1)]
    peak = max(logs)
    return min(1.0, math.exp(peak) * math.fsum(math.exp(v - peak) for v in logs))


def k_of(n, alpha):
    """Expected count k at which P(Poisson(k) ≤ n) == alpha (bisection)."""
    if n < 0 or int(n) != n or not 0 < alpha < 1:
        raise ValueError("invalid count/alpha")
    lo, hi = 0.0, max(1.0, n + 1.0)
    while pcdf(n, hi) > alpha:
        hi *= 2
    for _ in range(80):
        mid = (lo + hi) / 2
        if pcdf(n, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def thresholds(ltv, rule):
    cpa = ltv / rule["roas_target"]
    s_min = rule["min_spend_cpa_mult"] * cpa
    s_lead = max(rule["lead_spend_threshold"], s_min)
    mu = s_lead / (ltv * rule["p_max"])
    if pcdf(0, mu) >= rule["alpha"]:
        lead_n = None
    else:
        lead_n = 0
        while pcdf(lead_n + 1, mu) < rule["alpha"]:
            lead_n += 1
    return dict(cpa=cpa, s_min=s_min, s_lead=s_lead, lead_mu=mu, lead_n=lead_n)


def purchase_kill_spend(ltv, rule, n):
    t = thresholds(ltv, rule)
    return max(k_of(n, rule["alpha"]) * t["cpa"], t["s_min"])


def evaluate(spend, purchases, leads, lead_done, ltv, rule):
    """Decision for one adset. Returns dict(kill, tests=[...], lead_checked)."""
    t = thresholds(ltv, rule)
    if spend < t["s_min"]:
        return dict(kill=False, tests=[], lead_checked=False, below_min=True, t=t)
    tests = []
    lead_checked = False
    if not lead_done and spend >= t["s_lead"]:
        lead_checked = True
        bad = t["lead_n"] is not None and leads <= t["lead_n"]
        tests.append(dict(test="early stop (leads)", events=leads, threshold=t["lead_n"], failed=bad))
    limit = purchase_kill_spend(ltv, rule, purchases)
    tests.append(dict(test="stop (purchases)", events=purchases, threshold=round(limit, 2),
                      failed=spend > limit))
    return dict(kill=any(x["failed"] for x in tests), tests=tests, lead_checked=lead_checked,
                below_min=False, t=t)


def describe(pj):
    if pj["ltv"] is None:
        return f"{pj['name']}: ltv is not set — the rule never acts without it"
    r = pj["stop_rule"]
    t = thresholds(pj["ltv"], r)
    m = lambda v: common.money(pj, v)  # noqa: E731
    lines = [f"{pj['name']} · stop rule · campaigns '{r['campaign_prefix']}*'",
             f"LTV {m(pj['ltv'])} | CPA {m(t['cpa'])} | alpha {r['alpha']:.0%} | p_max {r['p_max']:.0%}",
             f"S_min {m(t['s_min'])} — never touched below",
             (f"early stop: once at spend ≥ {m(t['s_lead'])}, kill if {pj['lead_event']} ≤ {t['lead_n']} "
              f"(healthy ≥ {t['lead_mu']:.1f})") if t["lead_n"] is not None else
             f"early stop: no statistical power at {m(t['s_lead'])} — raise lead_spend_threshold or p_max",
             "stop: kill when lifetime spend exceeds"]
    lines += [f"  {n} purchase(s): {m(purchase_kill_spend(pj['ltv'], r, n))}" for n in range(6)]
    return "\n".join(lines)


def journal(row):
    common.STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = common.STATE_DIR / JOURNAL
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def run_project(pj, dry, state):
    r = pj["stop_rule"]
    if not r["enabled"]:
        return None
    if pj["ltv"] is None:
        return f"<b>{pj['name']}</b> · stop rule: ltv not set — nothing done"
    lines, kills, checked = [], 0, 0
    for acct in pj["accounts"]:
        camps = [c for c in common.get(f"{acct}/campaigns", fields="id,name,effective_status", limit=200)
                 if c["effective_status"] == "ACTIVE" and common.has_prefix(c["name"], r["campaign_prefix"])
                 and common.matches(pj, c["name"])]
        for c in camps:
            adsets = [s for s in common.get(f"{c['id']}/adsets", fields="id,name,effective_status", limit=200)
                      if s["effective_status"] == "ACTIVE"]
            if not adsets:
                continue
            rows = common.get(f"{c['id']}/insights", level="adset", date_preset="maximum",
                              fields="adset_id,spend,actions,conversions", limit=200)
            by_id = {x["adset_id"]: x for x in rows}
            for s in adsets:
                row = by_id.get(s["id"], {})
                spend = float(row.get("spend", 0))
                rec = state.setdefault(s["id"], {})
                d = evaluate(spend, common.act_val(row, pj["conversion_event"]),
                             common.act_val(row, pj["lead_event"]), rec.get("lead_done"), pj["ltv"], r)
                if d["below_min"]:
                    continue
                checked += 1
                if d["kill"]:
                    kills += 1
                    why = "; ".join(f"{x['test']}: {x['events']} vs ≤{x['threshold']}" if "lead" in x["test"]
                                    else f"{x['test']}: {x['events']} at spend > {common.money(pj, x['threshold'])}"
                                    for x in d["tests"] if x["failed"])
                    if dry:
                        tail = "would pause (dry run)"
                    else:
                        res = common.post(s["id"], {"status": "PAUSED"})
                        tail = "paused" if res.get("success") is True else f"PAUSE FAILED: {res}"
                    lines.append(f"⛔ {s['name']} ({c['name'][:30]}) · spend {common.money(pj, spend)} · {why} — <b>{tail}</b>")
                    if not dry and tail == "paused":
                        rec["paused_at"] = datetime.now(timezone.utc).isoformat()
                        journal(dict(stop_ts_utc=rec["paused_at"], project=pj["key"], campaign=c["name"],
                                     adset=s["name"], adset_id=s["id"], spend=round(spend, 2),
                                     purchases=d["tests"][-1]["events"], ltv=pj["ltv"], reason=why))
                if d["lead_checked"] and not dry:
                    rec["lead_done"] = True
                    rec["lead_result"] = d["tests"][0]
    head = f"<b>{pj['name']}</b> · test adsets stop rule"
    body = lines or [f"no stops — {checked} adset(s) above S_min checked, all within thresholds"]
    return head + "\n" + "\n".join(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="*")
    ap.add_argument("--dry", action="store_true", help="evaluate only, pause nothing, write no state")
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--describe", metavar="PROJECT")
    a = ap.parse_args()
    if a.describe:
        print(describe(common.load_project(a.describe)))
        return
    state = common.load_state(STATE)
    for pj in common.load_projects(a.projects):
        text = run_project(pj, a.dry, state)
        if not a.dry:
            common.save_state(STATE, state)
        if text:
            common.send(text) if a.telegram else print(text.replace("<b>", "").replace("</b>", ""), "\n")


if __name__ == "__main__":
    main()
