#!/usr/bin/env python3
"""Launch new creatives into the project's TEST campaign — one concept folder = one adset.

    python scripts/launch_tests.py <project> [--folder NAME ...] [--as NAME]
                                   [--geo US,GB] [--link URL] [--paused] [--dry]

Without --folder every not-yet-uploaded file (see creative_monitor.py) is
launched, grouped by its parent folder. Each group becomes a new adset in
`testing.campaign_id`, with all settings (targeting, optimization, attribution,
promoted object) copied from `testing.template_adset_id`, so adsets differ only
by creative — the campaign is a comparison of concepts. Ad name = file name.

Order per file: upload → (video: wait until ready, take preferred thumbnail)
→ creative → ad. Progress is journaled in run/deploy-<project>.json, so an
interrupted run resumes without duplicates; a lock file stops two concurrent
runs from creating the same ads twice.
"""
import argparse
import atexit
import base64
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ua_rules import common  # noqa: E402
import creative_monitor as mon  # noqa: E402

PROMOTED_KEYS = ("pixel_id", "custom_event_type", "custom_conversion_id",
                 "application_id", "object_store_url", "page_id")


def pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def take_lock(project):
    lockf = common.STATE_DIR / f"deploy-{project}.lock"
    common.STATE_DIR.mkdir(parents=True, exist_ok=True)
    if lockf.exists():
        try:
            old = int(lockf.read_text().split()[0])
        except Exception:
            old = -1
        if pid_alive(old):
            sys.exit(f"another launch for {project} is running (pid {old}) — a second one would create duplicates")
        print(f"stale lock from dead pid {old} removed")
    lockf.write_text(str(os.getpid()))
    atexit.register(lambda: lockf.exists() and lockf.unlink())


def adset_number(names):
    """Next NN for `NN. concept` naming, continuing the campaign's numbering."""
    used = [int(m.group(1)) for m in (re.match(r"\s*(\d+)\.", n) for n in names) if m]
    return max(used or [0]) + 1


def with_geo(targeting, countries):
    """Replace exactly the country list; everything else stays from the template.
    Regions/cities of the template would silently narrow the new countries."""
    tg = json.loads(json.dumps(targeting))
    geo = tg.setdefault("geo_locations", {})
    geo["countries"] = countries
    for k in ("regions", "cities", "zips", "places", "geo_markets"):
        geo.pop(k, None)
    return tg


def collect(pj, folders, merge_as):
    """Return {concept: [paths]} of files not yet in the account."""
    c = pj["creatives"]
    known, err = mon.known_names(pj)
    if err:
        sys.exit(f"account not readable ({err}) — refusing to launch: can't tell what is already uploaded")
    already = mon.make_already(known)
    groups = {}
    if folders:
        for f in folders:
            # A live folder wins over an archived one with the same name.
            src = next((p for p in (os.path.join(c["dir"], f), os.path.join(c["dir"], "_new", f))
                        if os.path.isdir(p)), None)
            if not src:
                print("no such folder:", f)
                continue
            files = [os.path.join(src, n) for n in sorted(mon.patient(os.listdir, src))
                     if n.lower().endswith(mon.MEDIA)]
            groups.setdefault(merge_as or f, []).extend(
                p for p in files if not already(mon.norm(p)))
    else:
        files, unread = mon.scan_folder(c["dir"], c["include"], c["exclude"])
        if unread:
            print(f"warning: {len(unread)} files not readable (drive busy) — they are skipped this run")
        for p, _, _ in files:
            if not already(mon.norm(p)):
                groups.setdefault(merge_as or os.path.basename(os.path.dirname(p)), []).append(p)
    return {k: v for k, v in groups.items() if v}


def wait_ready(video_id, tries=60):
    for _ in range(tries):
        st = (common.get(video_id, fields="status").get("status") or {}).get("video_status")
        if st == "ready":
            return True
        if st == "error":
            return False
        time.sleep(10)
    return False


def thumbnail(video_id):
    """A video creative needs image_url (Graph error subcode 1443226 otherwise)."""
    thumbs = common.get(f"{video_id}/thumbnails", fields="uri,is_preferred")
    if not isinstance(thumbs, list) or not thumbs:
        return None
    return next((t["uri"] for t in thumbs if t.get("is_preferred")), thumbs[0]["uri"])


def creative_spec(t, name, video_id=None, image_url=None, image_hash=None):
    """object_story_spec for a video or a single image. Empty texts are NOT sent:
    a text on one adset and none on the others becomes a second test variable."""
    cta = {"type": t["cta"], "value": {"link": t["link"]}}
    if t.get("link_caption"):
        cta["value"]["link_caption"] = t["link_caption"]
    story = {"page_id": t["page_id"]}
    if t.get("instagram_user_id"):
        story["instagram_user_id"] = t["instagram_user_id"]
    if video_id:
        data = {"video_id": video_id, "image_url": image_url, "call_to_action": cta}
        if t.get("title"):
            data["title"] = t["title"]
        story["video_data"] = data
    else:
        data = {"image_hash": image_hash, "link": t["link"], "call_to_action": cta}
        if t.get("title"):
            data["name"] = t["title"]
        if t.get("link_caption"):
            data["caption"] = t["link_caption"]
        story["link_data"] = data
    if t.get("message"):
        data["message"] = t["message"]
    body = {"name": name, "object_story_spec": story}
    if t.get("url_tags"):
        body["url_tags"] = t["url_tags"]
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--folder", action="append", default=[], help="concept folder; repeatable")
    ap.add_argument("--as", dest="merge_as", help="merge all --folder into ONE adset with this name")
    ap.add_argument("--geo", help="comma-separated ISO countries; default = template adset's")
    ap.add_argument("--link", help="destination URL; default = testing.link")
    ap.add_argument("--paused", action="store_true", help="create adsets and ads PAUSED")
    ap.add_argument("--dry", action="store_true", help="show the plan, create nothing")
    a = ap.parse_args()

    pj = common.load_project(a.project)
    t = dict(pj["testing"])
    if a.link:
        t["link"] = a.link
    missing = [k for k in ("campaign_id", "template_adset_id", "page_id", "link") if not t.get(k)]
    if missing or not pj["accounts"] or not pj["creatives"]["dir"]:
        sys.exit(f"{a.project}: set testing.{', testing.'.join(missing) or '…'}, accounts, creatives.dir")
    geo = [c.strip().upper() for c in a.geo.split(",")] if a.geo else None
    if geo and not all(re.fullmatch(r"[A-Z]{2}", c) for c in geo):
        sys.exit("geo must be 2-letter country codes: " + a.geo)
    status = "PAUSED" if a.paused else t["status"]
    acct = pj["accounts"][0]

    groups = collect(pj, a.folder, a.merge_as)
    total = sum(len(v) for v in groups.values())
    budget = float(t["daily_budget"])
    print(f"to launch: {total} creatives in {len(groups)} adset(s) · {common.money(pj, budget)}/day each "
          f"· +{common.money(pj, budget * len(groups))}/day total · status {status}")
    if geo:
        print("geo:", ", ".join(geo), "(instead of template's)")
    for g, fs in groups.items():
        print(f"  {g} — {len(fs)}")
        for p in fs:
            print("     ", os.path.basename(p))
    if a.dry or not total:
        return

    take_lock(a.project)
    statef = f"deploy-{a.project}.json"
    state = common.load_state(statef)
    for k in ("adsets", "media", "ads"):
        state.setdefault(k, {})

    def persist():
        common.save_state(statef, state)

    src = common.get(t["template_adset_id"], fields="targeting,attribution_spec,promoted_object,"
                     "billing_event,optimization_goal,bid_strategy,bid_amount,destination_type")
    targeting = with_geo(src["targeting"], geo) if geo else src["targeting"]
    nxt = adset_number(s["name"] for s in common.get(f"{t['campaign_id']}/adsets", fields="name", limit=200))

    for concept in groups:
        if concept in state["adsets"]:
            continue
        body = {
            "name": "%02d. %s" % (nxt, concept),
            "campaign_id": t["campaign_id"],
            "daily_budget": str(int(round(budget * 100))),
            "billing_event": src["billing_event"],
            "optimization_goal": src["optimization_goal"],
            "targeting": targeting,
            "status": status,
        }
        for k in ("bid_strategy", "bid_amount", "attribution_spec", "destination_type"):
            if src.get(k):
                body[k] = src[k]
        if src.get("promoted_object"):
            body["promoted_object"] = {k: v for k, v in src["promoted_object"].items() if k in PROMOTED_KEYS}
        d = common.post(f"{acct}/adsets", body)
        if "id" not in d:
            print(f"FAILED adset {concept}: {json.dumps(d, ensure_ascii=False)[:300]}")
            continue
        state["adsets"][concept] = d["id"]
        nxt += 1
        persist()
        print(f"adset {body['name']} → {d['id']}")

    created = 0
    for concept, files in groups.items():
        adset_id = state["adsets"].get(concept)
        if not adset_id:
            continue
        for p in files:
            name = os.path.splitext(os.path.basename(p))[0]
            if name in state["ads"]:
                continue
            is_video = p.lower().endswith(mon.VIDEO)
            media = state["media"].get(name)
            if not media:
                if is_video:
                    r = common.upload_file(f"{acct}/advideos", {"name": name}, "source", p)
                    media = r.get("id") and {"video_id": r["id"]}
                else:
                    with open(p, "rb") as fh:
                        r = common.post(f"{acct}/adimages", {"bytes": base64.b64encode(fh.read()).decode(),
                                                            "name": os.path.basename(p)})
                    img = next(iter((r.get("images") or {}).values()), {})
                    media = img.get("hash") and {"image_hash": img["hash"]}
                if not media:
                    print("  ✗ upload", name, json.dumps(r, ensure_ascii=False)[:200])
                    continue
                state["media"][name] = media
                persist()
            if is_video:
                if not wait_ready(media["video_id"]):
                    print("  ✗ video not ready", name)
                    continue
                thumb = thumbnail(media["video_id"])
                if not thumb:
                    print("  ✗ no thumbnail", name)
                    continue
                spec = creative_spec(t, name, video_id=media["video_id"], image_url=thumb)
            else:
                spec = creative_spec(t, name, image_hash=media["image_hash"])
            cr = common.post(f"{acct}/adcreatives", spec)
            if "id" not in cr:
                print("  ✗ creative", name, json.dumps(cr, ensure_ascii=False)[:220])
                continue
            ad = common.post(f"{acct}/ads", {"name": name, "adset_id": adset_id,
                                             "creative": {"creative_id": cr["id"]}, "status": status})
            if "id" not in ad:
                print("  ✗ ad", name, json.dumps(ad, ensure_ascii=False)[:220])
                continue
            state["ads"][name] = ad["id"]
            persist()
            created += 1
            print(f"  ✓ {name} → {ad['id']}")

    print(f"\nthis run: {len([c for c in groups if c in state['adsets']])} adset(s), {created} new ad(s)")


if __name__ == "__main__":
    main()
