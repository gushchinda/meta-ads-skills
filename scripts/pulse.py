#!/usr/bin/env python3
"""Test pulse — morning creative-test rotation + one HTML status page.

    python scripts/pulse.py [project ...] [--dry] [--telegram] [--out DIR]
                            [--lang en|ru] [--tz Area/City]

Model: each project has `rotation.max_slots` concurrent tests. A test = one
concept folder = one adset in the TEST campaign, with a spend cap
(`test_cap`, default ltv × cap_ltv_mult) spread over `test_days`
(daily budget = cap / days). Every morning:

1. Reconcile managed tests with Meta. A test that is no longer ACTIVE was
   paused by someone else (usually test-adset-stop) → EARLY_STOP, slot freed,
   with the stop rule's receipt attached. Never re-pause, never resume.
2. End tests that reached their cap or their age → pause, slot freed.
3. Queue = folders with not-yet-uploaded creatives (creative_monitor check),
   FIFO by first time seen; `rotation.hold` folders wait.
4. Free slots: with `rotation.enabled: true` launch the next folders
   (launch_tests.launch, daily = cap/days); otherwise only propose.
   More active tests than slots (manual or legacy adsets) = overflow:
   no launches, nothing is stopped to make room.
5. Write run/test-pulse-<date>.html (pulse_report.py) and a short summary.

`max_slots: 0` = queue-only project: the queue is reported, nothing launches.
ACTIVE adsets in TEST campaigns that this script did not launch are "legacy":
they occupy slots but are never touched. Weekly TEST spend vs
`rotation.weekly_guide` is informational and never blocks a launch.
"""
import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ua_rules import common  # noqa: E402
import creative_monitor as mon  # noqa: E402
import launch_tests as lt  # noqa: E402
import pulse_report  # noqa: E402

LIVE = ("ACTIVE", "IN_PROCESS", "WITH_ISSUES", "PENDING_REVIEW")


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
    if effective_status not in LIVE:
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


def age_days(since_iso, now):
    t = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return round((now - t).total_seconds() / 86400, 2)


def slot_state(active, max_slots, free_after, queue_ready):
    if max_slots == 0:
        return "queue_only"
    if active > max_slots:
        return "overflow"
    if free_after == 0:
        return "full"
    return "free_no_queue" if not queue_ready else "free"


def geo_of(targeting):
    g = (targeting or {}).get("geo_locations") or {}
    x = (targeting or {}).get("excluded_geo_locations") or {}
    return g.get("countries") or [], x.get("countries") or []


# --- Meta reads -----------------------------------------------------------

ADSET_FIELDS = "id,name,status,effective_status,daily_budget,created_time,campaign_id,targeting"


def test_campaigns(pj):
    prefix = pj["testing"]["campaign_prefix"]
    out = []
    for acct in pj["accounts"]:
        out += [c for c in common.get(f"{acct}/campaigns", fields="id,name,effective_status", limit=200)
                if c["effective_status"] == "ACTIVE" and common.has_prefix(c["name"], prefix)
                and common.matches(pj, c["name"])]
    return out


def events_of(pj, row):
    names = [pj["conversion_event"], pj["lead_event"]] + list(pj["rotation"].get("extra_events") or [])
    return {e: common.act_val(row, e) for e in dict.fromkeys(names)}


def read_tests(pj, camps, managed_ids, window_since):
    """adsets {id: {...}} with lifetime spend/events, per-ad delivery and Meta issues."""
    adsets, ads_window, issues = {}, [], {}
    for c in camps:
        for s in common.get(f"{c['id']}/adsets", fields=ADSET_FIELDS, limit=200):
            if s["effective_status"] in LIVE or s["id"] in managed_ids:
                adsets[s["id"]] = dict(s, spend=0.0, events=events_of(pj, {}), ads=0, delivered=0)
        for r in common.get(f"{c['id']}/insights", level="adset", date_preset="maximum",
                            fields="adset_id,spend,actions,conversions", limit=200):
            a = adsets.get(r["adset_id"])
            if a:
                a.update(spend=float(r["spend"]), events=events_of(pj, r))
        delivered = {r["ad_id"] for r in common.get(f"{c['id']}/insights", level="ad", date_preset="maximum",
                                                    fields="ad_id,impressions", limit=500)
                     if int(r.get("impressions", 0)) > 0}
        for ad in common.get(f"{c['id']}/ads", fields="id,adset_id,effective_status,created_time,issues_info",
                             limit=500):
            if (ad.get("created_time") or "")[:10] >= window_since.isoformat():
                ads_window.append(ad["id"] in delivered)
            a = adsets.get(ad["adset_id"])
            if not a:
                continue
            a["ads"] += 1
            a["delivered"] += ad["id"] in delivered
            for i in ad.get("issues_info") or []:
                k = (i.get("error_type", ""), str(i.get("error_code", "")), i.get("error_summary", ""))
                issues.setdefault(k, set()).add(ad["id"])
    for sid in managed_ids - adsets.keys():
        try:
            s = common.get(sid, fields=ADSET_FIELDS)
        except common.GraphError:
            s = dict(id=sid, name="", status="DELETED", effective_status="DELETED")
        adsets[sid] = dict(s, spend=0.0, events=events_of(pj, {}), ads=0, delivered=0)
    issue_rows = [dict(type=k[0], code=k[1], summary=k[2], ads=len(v)) for k, v in issues.items()]
    return adsets, ads_window, issue_rows


def insights_sum(camps, preset):
    total = 0.0
    for c in camps:
        for r in common.get(f"{c['id']}/insights", level="campaign", date_preset=preset, fields="spend", limit=10):
            total += float(r["spend"])
    return total


def account_info(pj):
    try:
        a = common.get(pj["accounts"][0], fields="timezone_name,currency")
        return a.get("timezone_name", ""), a.get("currency", pj["currency"])
    except Exception:  # noqa: BLE001
        return "", pj["currency"]


def uploaded_videos(pj, since, until):
    n = 0
    for acct in pj["accounts"]:
        for v in common.get(f"{acct}/advideos", fields="id,created_time", limit=500):
            if since.isoformat() <= (v.get("created_time") or "")[:10] <= until.isoformat():
                n += 1
    return n


def folder_files(pj, since, until):
    d = pj["creatives"]["dir"]
    if not d or not os.path.isdir(d):
        return None
    lo = datetime.combine(since, datetime.min.time()).timestamp()
    hi = datetime.combine(until + timedelta(days=1), datetime.min.time()).timestamp()
    files, _ = mon.scan_folder(d, [], [], mon.VIDEO)
    return sum(1 for _, mt, _ in files if lo <= mt < hi)


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
    today = now.date()
    m_since, m_until = today - timedelta(days=30), today - timedelta(days=1)

    tz, cur = account_info(pj)
    camps = test_campaigns(pj)
    live, ads_window, issues = read_tests(pj, camps, running, m_since)
    stop_receipts = common.load_state("stop-rule.json")
    res = dict(pj=pj, tz=tz, currency=cur, cap=cap, days=days, daily=daily, ended=[], launched=[], proposed=[],
               errors=[], issues=issues, mode="queue_only" if r["max_slots"] == 0 else "rotation")

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
        rec = stop_receipts.get(sid, {})
        res["ended"].append(dict(name=t["name"], folder=t.get("folder", t["name"]), id=sid, reason=why,
                                 spend=a.get("spend", 0.0), events=a.get("events", {}), age=age, days=t["days"],
                                 receipt=rec if why == "EARLY_STOP" else {}, dry=dry and why != "EARLY_STOP",
                                 replacement=None))
        if not dry:
            t.update(status="ENDED", end_reason=why, ended_at=now.isoformat(), spend_at_end=a.get("spend", 0.0))
    ended_ids = {e["id"] for e in res["ended"]}
    still = [sid for sid in running if sid not in ended_ids]
    legacy = [sid for sid, a in live.items() if sid not in st["tests"] and a["effective_status"] in LIVE]
    daily_of = lambda sid: float(live.get(sid, {}).get("daily_budget") or 0) / 100  # noqa: E731
    res["daily_before"] = sum(daily_of(s) for s in still + legacy)

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
    hold = set(r["hold"])
    order = fifo(st["queue"], hold)

    # 4. free slots (overflow → none)
    active_before = len(still) + len(legacy)
    free = max(0, r["max_slots"] - active_before)
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
                                    days=days, status="RUNNING", creatives=len(groups[g]))
            try:
                back = common.get(sid, fields=ADSET_FIELDS)
            except common.GraphError:
                back = {}
            live[sid] = dict(back, spend=0.0, events=events_of(pj, {}), ads=len(groups[g]), delivered=0)
            countries, excluded = geo_of(back.get("targeting"))
            res["launched"].append(dict(folder=folder, id=sid, name=back.get("name", folder), count=len(groups[g]),
                                        campaign_id=back.get("campaign_id", ""), geo=countries, excluded=excluded,
                                        status=back.get("status", "?"), effective_status=back.get("effective_status", "?"),
                                        end=(now + timedelta(days=days)).isoformat(timespec="minutes")))
            still.append(sid)
    for e, x in zip([e for e in res["ended"]], res["launched"]):
        e["replacement"] = x
    if not dry:
        common.save_state(statef, st)

    # tests list (managed first, then legacy)
    res["tests"] = []
    for sid in still + legacy:
        a, t = live.get(sid, {}), st["tests"].get(sid)
        countries, excluded = geo_of(a.get("targeting"))
        since = t["launched_at"] if t else a.get("created_time") or now.isoformat()
        res["tests"].append(dict(id=sid, name=a.get("name") or (t or {}).get("name", sid), managed=bool(t),
                                 status=a.get("status", "?"), effective_status=a.get("effective_status", "?"),
                                 campaign_id=a.get("campaign_id", ""), geo=countries, excluded=excluded,
                                 daily=daily_of(sid), age=age_days(since, now), days=(t or {}).get("days", days),
                                 cap=(t or {}).get("cap"), spend=a.get("spend", 0.0), events=a.get("events", {}),
                                 ads=a.get("ads", 0), delivered=a.get("delivered", 0)))
    active = len(still) + len(legacy)
    res["slots"] = dict(active=active, max=r["max_slots"], free=max(0, r["max_slots"] - active),
                        new=len(res["launched"]))
    res["queue"] = [dict(folder=g, count=st["queue"][g].get("count", 0), first_seen=st["queue"][g]["first_seen"],
                         hold=g in hold) for g in sorted(st["queue"], key=lambda k: st["queue"][k]["first_seen"])]
    ready = [q for q in res["queue"] if not q["hold"]]
    res["slot_state"] = slot_state(active_before, r["max_slots"], res["slots"]["free"], ready)
    res["daily_after"] = res["daily_before"] + sum(daily or 0 for _ in res["launched"])

    # week (informational) and 30 full days
    monday = today - timedelta(days=today.weekday())
    spend = insights_sum(camps, "this_week_mon_today")
    reserve = sum(max(0.0, (x["cap"] or cap or 0) - x["spend"]) for x in res["tests"])
    guide = r["weekly_guide"]
    res["week"] = dict(since=monday, until=today, spend=spend, guide=guide, reserve=reserve,
                       left=(guide - spend - reserve) if guide else None,
                       prev=insights_sum(camps, "last_week_mon_sun"))
    finished = sum(v.get("creatives", 0) for v in st["tests"].values()
                   if v["status"] == "ENDED" and (v.get("ended_at") or "")[:10] >= m_since.isoformat())
    zero_managed = [x for x in res["tests"] if x["managed"]]
    res["month"] = dict(since=m_since, until=m_until, target=r.get("monthly_target"),
                        files=folder_files(pj, m_since, m_until), uploaded=uploaded_videos(pj, m_since, m_until),
                        finished=finished, zero_window=(ads_window.count(False), len(ads_window)),
                        zero_managed=(sum(x["ads"] - x["delivered"] for x in zero_managed if x["age"] >= 1),
                                      sum(x["ads"] for x in zero_managed)))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="*")
    ap.add_argument("--dry", action="store_true", help="no pauses, no launches, no state writes")
    ap.add_argument("--telegram", action="store_true")
    ap.add_argument("--out", default=str(common.STATE_DIR), help="directory for test-pulse-<date>.html")
    ap.add_argument("--lang", default=os.environ.get("PULSE_LANG", "en"), choices=sorted(pulse_report.T))
    ap.add_argument("--tz", default=os.environ.get("PULSE_TZ"), help="show times also in this zone, e.g. Europe/Berlin")
    a = ap.parse_args()
    now = datetime.now(timezone.utc)
    results = [run_project(pj, a.dry, now) for pj in common.load_projects(a.projects)]
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"test-pulse-{now:%Y-%m-%d}.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(pulse_report.html_page(results, now, a.dry, a.lang, a.tz))
    for res in results:
        text = pulse_report.summary(res, a.dry, a.lang)
        common.send(text) if a.telegram else print(text.replace("<b>", "").replace("</b>", ""), "\n")
    print("report:", path)


if __name__ == "__main__":
    main()
