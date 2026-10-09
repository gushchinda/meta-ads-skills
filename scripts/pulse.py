#!/usr/bin/env python3
"""Test pulse — morning creative-test rotation + one HTML status page.

    python scripts/pulse.py [project ...] [--dry] [--telegram] [--out DIR]

Model: each project has `rotation.max_slots` concurrent tests. A test = one
concept folder = one adset in the TEST campaign, with a spend cap
(`test_cap`, default ltv × cap_ltv_mult) spread over `test_days`
(daily budget = cap / days). Every morning:

1. Reconcile managed tests with Meta. A test that is no longer ACTIVE was
   paused by someone else (usually test-adset-stop) → EARLY_STOP, slot freed.
   Never re-pause, never resume.
2. End tests that reached their cap or their age → pause, slot freed.
3. Queue = folders with not-yet-uploaded creatives (creative_monitor check),
   FIFO by first time seen; `rotation.hold` folders wait.
4. Free slots: with `rotation.enabled: true` launch the next folders
   (launch_tests.launch, daily = cap/days); otherwise only propose.
5. Write run/test-pulse-<date>.html and print / send a short summary.

ACTIVE adsets in TEST campaigns that this script did not launch are "legacy":
they occupy slots but are never touched. Weekly TEST spend vs
`rotation.weekly_guide` is informational and never blocks a launch.
"""
import argparse
import html
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ua_rules import common  # noqa: E402
import creative_monitor as mon  # noqa: E402
import launch_tests as lt  # noqa: E402


# --- pure rules (unit-tested) ---------------------------------------------

def test_cap(pj):
    r = pj["rotation"]
    if r["test_cap"]:
        return float(r["test_cap"])
    return None if pj["ltv"] is None else round(pj["ltv"] * r["cap_ltv_mult"], 2)


def daily_for(cap, days):
    return round(cap / days, 2)


def end_reason(effective_status, spend, cap, age_days, days):
    """Why a managed test is over, or None if it keeps running."""
    if effective_status not in ("ACTIVE", "IN_PROCESS", "WITH_ISSUES"):
        return "EARLY_STOP"          # paused outside the rotation (stop rule, a human)
    if cap is not None and spend >= cap:
        return "CAP"
    if age_days >= days:
        return "AGE"
    return None


def fifo(queue, hold):
    """Ready folders in launch order: oldest first_seen first, held ones excluded."""
    ready = [(v["first_seen"], k) for k, v in queue.items() if k not in hold]
    return [k for _, k in sorted(ready)]


def age_days(launched_at, now):
    return round((now - datetime.fromisoformat(launched_at)).total_seconds() / 86400, 2)


# --- Meta reads -----------------------------------------------------------

def test_campaigns(pj):
    prefix = pj["testing"]["campaign_prefix"]
    out = []
    for acct in pj["accounts"]:
        out += [c for c in common.get(f"{acct}/campaigns", fields="id,name,effective_status", limit=200)
                if c["effective_status"] == "ACTIVE" and common.has_prefix(c["name"], prefix)
                and common.matches(pj, c["name"])]
    return out


def read_tests(pj, camps, managed_ids):
    """adsets {id: {...}} with lifetime spend/events and per-ad delivery."""
    adsets = {}
    for c in camps:
        for s in common.get(f"{c['id']}/adsets", fields="id,name,status,effective_status,daily_budget", limit=200):
            if s["effective_status"] == "ACTIVE" or s["id"] in managed_ids:
                adsets[s["id"]] = dict(s, campaign=c["name"], spend=0.0, conv=0, leads=0, ads=0, delivered=0)
        for r in common.get(f"{c['id']}/insights", level="adset", date_preset="maximum",
                            fields="adset_id,spend,actions,conversions", limit=200):
            a = adsets.get(r["adset_id"])
            if a:
                a.update(spend=float(r["spend"]), conv=common.act_val(r, pj["conversion_event"]),
                         leads=common.act_val(r, pj["lead_event"]))
        delivered = {r["ad_id"] for r in common.get(f"{c['id']}/insights", level="ad", date_preset="maximum",
                                                    fields="ad_id,impressions", limit=500)
                     if int(r.get("impressions", 0)) > 0}
        for ad in common.get(f"{c['id']}/ads", fields="id,adset_id", limit=500):
            a = adsets.get(ad["adset_id"])
            if a:
                a["ads"] += 1
                a["delivered"] += ad["id"] in delivered
    # managed tests whose campaign is no longer ACTIVE
    for sid in managed_ids - adsets.keys():
        s = common.get(sid, fields="id,name,status,effective_status")
        adsets[sid] = dict(s, campaign="", spend=0.0, conv=0, leads=0, ads=0, delivered=0)
    return adsets


def week_spend(camps):
    total = 0.0
    for c in camps:
        for r in common.get(f"{c['id']}/insights", level="campaign", date_preset="this_week_mon_today",
                            fields="spend", limit=10):
            total += float(r["spend"])
    return total


# --- one project ----------------------------------------------------------

def run_project(pj, dry, now):
    r = pj["rotation"]
    cap = test_cap(pj)
    days = r["test_days"]
    daily = daily_for(cap, days) if cap else None
    statef = f"pulse-{pj['key']}.json"
    st = common.load_state(statef)
    st.setdefault("tests", {})
    st.setdefault("queue", {})
    running = {k for k, v in st["tests"].items() if v["status"] == "RUNNING"}

    camps = test_campaigns(pj)
    live = read_tests(pj, camps, running)
    res = dict(pj=pj, cap=cap, days=days, daily=daily, ended=[], launched=[], proposed=[], errors=[])

    # 1-2. reconcile and end
    for sid in sorted(running):
        t, a = st["tests"][sid], live.get(sid, {})
        age = age_days(t["launched_at"], now)
        why = end_reason(a.get("effective_status", "DELETED"), a.get("spend", 0.0), t.get("cap"), age, t["days"])
        if not why:
            continue
        if why in ("CAP", "AGE") and not dry:
            p = common.post(sid, {"status": "PAUSED"})
            if p.get("success") is not True:
                res["errors"].append(f"pause {t['name']} failed: {p}")
                continue
        res["ended"].append(dict(name=t["name"], id=sid, reason=why, spend=a.get("spend", 0.0),
                                 conv=a.get("conv", 0), dry=dry and why != "EARLY_STOP"))
        if not dry:
            t.update(status="ENDED", end_reason=why, ended_at=now.isoformat(), spend_at_end=a.get("spend", 0.0),
                     conv_at_end=a.get("conv", 0))
    ended_ids = {e["id"] for e in res["ended"]}
    still = [sid for sid in running if sid not in ended_ids]
    legacy = [sid for sid, a in live.items() if sid not in st["tests"] and a["effective_status"] == "ACTIVE"]

    # 3. queue
    try:
        groups = lt.collect(pj, [], None) if pj["creatives"]["dir"] else {}
    except SystemExit as e:
        groups = {}
        res["errors"].append(f"queue not built: {e}")
    for g, files in groups.items():
        st["queue"].setdefault(g, {"first_seen": now.isoformat()})["count"] = len(files)
    for g in list(st["queue"]):
        if g not in groups:
            st["queue"].pop(g)
    order = fifo(st["queue"], set(r["hold"]))

    # 4. free slots
    free = max(0, r["max_slots"] - len(still) - len(legacy))
    for g in order[:free]:
        if not (r["enabled"] and cap) or dry:
            res["proposed"].append(dict(folder=g, count=len(groups[g])))
            continue
        try:
            done = lt.launch(pj, {g: groups[g]}, daily_budget=daily, geo=r.get("geo"))
        except SystemExit as e:
            res["errors"].append(f"launch {g}: {e}")
            continue
        for folder, sid in done.items():
            st["tests"][sid] = dict(name=folder, folder=folder, launched_at=now.isoformat(), cap=cap,
                                    days=days, status="RUNNING")
            res["launched"].append(dict(folder=folder, id=sid, count=len(groups[g])))
            still.append(sid)
    if not dry:
        common.save_state(statef, st)

    res["tests"] = [dict(live.get(sid, {}), **st["tests"][sid], age=age_days(st["tests"][sid]["launched_at"], now),
                         managed=True) for sid in still if sid in st["tests"]]
    res["legacy"] = [dict(live[sid], managed=False) for sid in legacy]
    res["slots"] = dict(active=len(still) + len(legacy), max=r["max_slots"])
    res["queue"] = [dict(folder=g, count=st["queue"][g].get("count", 0), first_seen=st["queue"][g]["first_seen"],
                         hold=g in r["hold"]) for g in sorted(st["queue"], key=lambda k: st["queue"][k]["first_seen"])]
    res["week"] = week_spend(camps)
    res["reserve"] = sum(max(0.0, (t.get("cap") or 0) - t.get("spend", 0.0)) for t in res["tests"])
    res["guide"] = r["weekly_guide"]
    return res


# --- output ---------------------------------------------------------------

def summary(res, dry):
    pj, m = res["pj"], lambda v: common.money(res["pj"], v)
    s = res["slots"]
    lines = [f"<b>{pj['name']}</b> · test pulse · slots {s['active']}/{s['max']}"
             + (f" · cap {m(res['cap'])} / {res['days']} d = {m(res['daily'])}/day" if res["cap"] else " · ltv not set")]
    for e in res["ended"]:
        lines.append(f"⏹ {e['name']} — {e['reason']}{' (dry)' if e['dry'] else ''} · {m(e['spend'])}, "
                     f"{e['conv']} {pj['conversion_event']}")
    for x in res["launched"]:
        lines.append(f"▶️ launched {x['folder']} ({x['count']} creatives) → {x['id']}")
    for x in res["proposed"]:
        lines.append(f"⏭ next: {x['folder']} ({x['count']}) — "
                     + ("dry run" if dry else "rotation.enabled is off, launch with launch_tests.py"))
    free = s["max"] - s["active"]
    if free > 0 and not res["launched"] and not res["proposed"]:
        lines.append(f"{free} free slot(s), queue is empty — need new creatives")
    q = [x for x in res["queue"] if not x["hold"]]
    lines.append(f"queue: {len(q)} folder(s) / {sum(x['count'] for x in q)} creatives"
                 + (f" · week TEST spend {m(res['week'])} / {m(res['guide'])}" if res["guide"] else
                    f" · week TEST spend {m(res['week'])}"))
    lines += [f"⚠️ {e}" for e in res["errors"]]
    return "\n".join(lines)


CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--mute:#6e6e73;--line:#e3e1dc;--bar:#e9e7e2;--ok:#2f7d4f;--warn:#b26b00;--bad:#b3261e;--acc:#3557c4}
@media (prefers-color-scheme:dark){:root{--bg:#141414;--card:#1e1e1f;--ink:#f2f2f2;--mute:#a1a1a6;--line:#333;--bar:#2c2c2e;--ok:#5cc489;--warn:#e7a33e;--bad:#ff6b5e;--acc:#7d9bff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,system-ui,Segoe UI,Roboto,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 48px}h1{font-size:26px;margin:0 0 4px}.mute{color:var(--mute)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin:16px 0}
.head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}.slots{font-size:30px;font-weight:700}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-top:12px}
.test{border:1px solid var(--line);border-radius:10px;padding:12px}.test b{word-break:break-word}
.bar{height:8px;background:var(--bar);border-radius:4px;overflow:hidden;margin:4px 0 8px}.bar i{display:block;height:100%;background:var(--acc)}
.bar i.hot{background:var(--warn)}.tag{font-size:12px;padding:2px 8px;border-radius:999px;border:1px solid var(--line);color:var(--mute)}
.ev{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}.ev li{list-style:none;margin:0;font-size:13px}
ul{padding-left:18px;margin:6px 0}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
"""


def bar(v, top):
    pct = 0 if not top else min(100, 100 * v / top)
    return f'<div class="bar"><i class="{"hot" if pct >= 85 else ""}" style="width:{pct:.0f}%"></i></div>'


def html_page(results, now, dry):
    e = html.escape
    parts = [f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
             f"<title>Test pulse {now:%d.%m.%Y}</title><style>{CSS}</style></head><body><main>",
             f"<h1>Test pulse · {now:%d.%m.%Y}</h1><div class=mute>snapshot {now:%Y-%m-%d %H:%M} UTC"
             f"{' · DRY RUN — nothing changed' if dry else ''} · "
             + " · ".join(f"{e(r['pj']['name'])} {r['slots']['active']}/{r['slots']['max']}" for r in results) + "</div>"]
    for r in results:
        pj, m = r["pj"], lambda v, p=r["pj"]: common.money(p, v)
        s = r["slots"]
        parts.append(f"<section class=card><div class=head><div><h2 style='margin:0'>{e(pj['name'])}</h2>"
                     f"<div class=mute>LTV {m(pj['ltv']) if pj['ltv'] else '—'} / {e(pj['conversion_event'])}"
                     + (f" · cap {m(r['cap'])} over {r['days']} d · {m(r['daily'])}/day" if r["cap"] else "")
                     + f"</div></div><div class=slots>{s['active']} / {s['max']}<div class='mute' style='font-size:13px;font-weight:400'>active / slots</div></div></div>")
        guide = r["guide"]
        parts.append(f"<p class=mute>Week TEST spend {m(r['week'])}" + (f" of guide {m(guide)}" if guide else "")
                     + f" · remaining caps of running tests {m(r['reserve'])} · informational, never blocks launches.</p>")
        if r["ended"] or r["launched"] or r["proposed"] or r["errors"]:
            parts.append("<ul>")
            parts += [f"<li class={'warn' if x['reason'] == 'EARLY_STOP' else 'mute'}>⏹ {e(x['name'])} — {x['reason']}"
                      f"{' (dry)' if x['dry'] else ''} · {m(x['spend'])} · {x['conv']} {e(pj['conversion_event'])}</li>" for x in r["ended"]]
            parts += [f"<li class=ok>▶ launched {e(x['folder'])} · {x['count']} creatives · {x['id']}</li>" for x in r["launched"]]
            parts += [f"<li>⏭ next in line: {e(x['folder'])} · {x['count']} creatives</li>" for x in r["proposed"]]
            parts += [f"<li class=bad>⚠ {e(x)}</li>" for x in r["errors"]]
            parts.append("</ul>")
        parts.append("<div class=grid>")
        for t in r["tests"] + r["legacy"]:
            # A test launched today is still in review: zero delivery there is noise.
            zero = t.get("ads", 0) - t.get("delivered", 0) if t.get("age", 99) >= 1 else 0
            if t["managed"]:
                prog = (f"<div class=mute>age {t['age']:.1f} / {t['days']} d</div>{bar(t['age'], t['days'])}"
                        f"<div class=mute>spend {m(t.get('spend', 0))} / {m(t['cap'])}</div>{bar(t.get('spend', 0), t['cap'])}")
                tag = "managed"
            else:
                prog = f"<div class=mute>lifetime spend {m(t.get('spend', 0))}</div>"
                tag = "legacy · not touched"
            parts.append(f"<div class=test><b>{e(t.get('name', ''))}</b> <span class=tag>{tag}</span>"
                         f"<div class=mute style='font-size:12px'>{e(t.get('id', ''))}</div>{prog}"
                         f"<div class=ev><li>{t.get('conv', 0)} {e(pj['conversion_event'])}</li><li>· {t.get('leads', 0)} {e(pj['lead_event'])}</li></div>"
                         + (f"<div class=warn style='font-size:13px'>zero delivery: {zero}/{t['ads']} ads</div>" if zero > 0 else "")
                         + "</div>")
        parts.append("</div>")
        q = r["queue"]
        parts.append("<h3>Queue</h3>" + ("<ul>" + "".join(
            f"<li>{e(x['folder'])} · {x['count']} creatives · since {x['first_seen'][:10]}{' · HOLD' if x['hold'] else ''}</li>"
            for x in q) + "</ul>" if q else "<p class=mute>No ready folders — free slots wait for new creatives.</p>"))
        parts.append("</section>")
    parts.append("<p class=mute>ACTIVE means switched on, not delivering. A finished test does not prove every creative "
                 "got enough delivery — check zero-delivery counts.</p></main></body></html>")
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="*")
    ap.add_argument("--dry", action="store_true", help="no pauses, no launches, no state writes")
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--out", default=str(common.STATE_DIR), help="directory for test-pulse-<date>.html")
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    results = [run_project(pj, a.dry, now) for pj in common.load_projects(a.projects)]
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"test-pulse-{now:%Y-%m-%d}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html_page(results, now, a.dry))
    for res in results:
        text = summary(res, a.dry)
        common.send(text) if a.telegram else print(text.replace("<b>", "").replace("</b>", ""), "\n")
    print("report:", path)


if __name__ == "__main__":
    main()
