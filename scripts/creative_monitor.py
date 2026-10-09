#!/usr/bin/env python3
"""Which creatives in a project's folder are NOT yet in its ad account.

    python scripts/creative_monitor.py [project ...] [--days N] [--all] [--telegram]

"New" is decided by scanning, not by folder conventions: a file is new when its
normalized name is absent from the account's ads, ad videos and ad images.
(Ad name == file name without extension is the convention all these skills
share.) People drop files wherever is convenient, so trusting a `_new/` folder
or a manifest misses batches; dates on synced drives lie (a re-sync stamps
"now" on yesterday's batch), so `--days` is only a filter on top.

Known blind spots: a renamed file looks new; a file uploaded under another name
is not detected. Content matching would need downloading every video from Meta,
which returns them re-encoded anyway.
"""
import argparse
import datetime
import errno
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ua_rules import common  # noqa: E402

VIDEO = (".mp4", ".mov", ".m4v")
IMAGE = (".png", ".jpg", ".jpeg")
MEDIA = VIDEO + IMAGE


def norm(name):
    """Comparable form: no extension, case, separators, leading batch number
    or ` (1)` copy suffix — `03_Sunset_v22.mp4` and `sunset v22` are the same."""
    s = os.path.splitext(os.path.basename(name))[0].lower()
    s = re.sub(r"^\d{1,3}[_\-. ]+", "", s)
    s = re.sub(r"\(\d+\)", "", s)
    return re.sub(r"[^a-z0-9а-яё]+", "", s)


def make_already(known):
    """Predicate "this normalized name is already in the account".

    Containment is checked one way only — a known name INSIDE the file name
    (a batch renamed to a convention: `hook 3` in the account,
    `02_summer_hook_3` on disk). The reverse direction gives false
    "uploaded" whenever a concept name equals a brand (`brandx` is inside
    `brandxtrunk`, a different creative). Short names (<5 chars) are matched
    exactly only: `1.1 (1).mp4` normalizes to `11`, found in half of all names.
    """
    exact = set(known)
    long_known = [k for k in exact if len(k) >= 5]

    def already(n):
        if n in exact:
            return True
        if len(n) < 5:
            return False
        return any(k in n for k in long_known)

    return already


def human_age(ts, now=None):
    """today · yesterday · N d ago — by calendar date, not by hours elapsed."""
    today = (now or datetime.datetime.now()).date()
    n = (today - datetime.datetime.fromtimestamp(ts).date()).days
    if n <= 0:
        return "today"
    if n == 1:
        return "yesterday"
    return f"{n} d ago"


def top_folder_allowed(rel, include, exclude):
    head = rel.split(os.sep)[0].lower() if rel not in (".", "") else "."
    if head == ".":
        return True
    if include and not any(head.startswith(i.lower()) for i in include):
        return False
    return not any(head.startswith(x.lower()) for x in exclude)


def patient(fn, *a, tries=4, pause=4):
    """Cloud-drive mounts answer "busy" while syncing (EAGAIN, Windows 1450/5/32).
    That is "retry", not "no file" — a silent skip is an incomplete answer
    presented as a complete one."""
    for i in range(tries):
        try:
            return fn(*a)
        except FileNotFoundError:
            raise
        except OSError as e:
            busy = getattr(e, "winerror", None) in (1450, 5, 32) or e.errno in (errno.EAGAIN, errno.EBUSY)
            if not busy or i == tries - 1:
                raise
            time.sleep(pause * (i + 1))


def scan_folder(root, include=(), exclude=(), exts=MEDIA):
    """Return ([(path, mtime, size)], [unread]) for media under root."""
    files, unread = [], []
    for d, dirs, names in os.walk(root, onerror=lambda e: unread.append(str(e)[:80])):
        rel = os.path.relpath(d, root)
        if not top_folder_allowed(rel, include, exclude):
            dirs[:] = []
            continue
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        for n in sorted(names):
            if not n.lower().endswith(exts):
                continue
            p = os.path.join(d, n)
            try:
                st = patient(os.stat, p)
            except OSError as e:
                unread.append(f"{os.path.relpath(p, root)} — {str(e)[:40]}")
                continue
            files.append((p, st.st_mtime, st.st_size))
    return files, unread


def account_names(accounts):
    known = set()
    for acct in accounts:
        for ad in common.get(f"{acct}/ads", fields="name", limit=400):
            known.add(norm(ad["name"]))
        for v in common.get(f"{acct}/advideos", fields="title", limit=300):
            if v.get("title"):
                known.add(norm(v["title"]))
        for im in common.get(f"{acct}/adimages", fields="name", limit=400):
            if im.get("name"):
                known.add(norm(im["name"]))
    return known


def known_names(pj):
    """Names already in the account(s), minus the ones a human withdrew
    ("treat this batch as untested again"). Returns (set, error_or_None)."""
    try:
        known = account_names(pj["accounts"])
    except Exception as e:  # noqa: BLE001
        return set(), str(e)[:120]
    for w in pj["creatives"]["withdrawn"]:
        known.discard(norm(w))
    return known, None


def scan_project(pj, days=0, show_all=False):
    c = pj["creatives"]
    if not c["dir"]:
        return dict(error="creatives.dir is not set", rows=[], files=[], unread=[], account_error=None)
    files, unread = scan_folder(c["dir"], c["include"], c["exclude"])
    known, acct_err = known_names(pj)
    already = make_already(known)
    cutoff = time.time() - days * 86400 if days else 0
    rows = []
    for p, mt, sz in files:
        if mt < cutoff:
            continue
        new = not already(norm(p))
        if new or show_all:
            rows.append(dict(path=p, rel=os.path.relpath(p, c["dir"]), mtime=mt, size=sz, new=new))
    rows.sort(key=lambda r: -r["mtime"])
    return dict(error=None, rows=rows, files=files, unread=unread, account_error=acct_err,
                known=len(known))


def by_folder(rows):
    out = {}
    for r in rows:
        if r["new"]:
            out.setdefault(os.path.dirname(r["rel"]) or ".", []).append(r)
    return dict(sorted(out.items(), key=lambda kv: -max(x["mtime"] for x in kv[1])))


def message(pj, res):
    head = f"<b>{pj['name']}</b> · new creatives"
    if res["error"]:
        return f"{head}\n{res['error']}"
    lines = [head]
    if res["account_error"]:
        lines.append("⚠️ account not readable — list below is EVERYTHING in the folder, "
                     f"not what's missing ({res['account_error']})")
    if res["unread"]:
        lines.append(f"⚠️ {len(res['unread'])} files not readable (drive busy) — count is incomplete")
    groups = by_folder(res["rows"])
    if not groups:
        lines.append("nothing new — every file is already in the account")
        return "\n".join(lines)
    total = sum(len(v) for v in groups.values())
    lines.append(f"{total} not uploaded, {len(groups)} folder(s):")
    for folder, items in groups.items():
        kinds = {"video" if i["path"].lower().endswith(VIDEO) else "image" for i in items}
        lines.append(f"• {folder} — {len(items)} {'/'.join(sorted(kinds))}, "
                     f"{human_age(max(i['mtime'] for i in items))}")
    lines.append("")
    lines.append("deploy: <code>python scripts/launch_tests.py %s --folder &lt;name&gt;</code>" % pj["key"])
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("projects", nargs="*")
    ap.add_argument("--days", type=int, default=0)
    ap.add_argument("--all", action="store_true", help="also list files already uploaded")
    ap.add_argument("--telegram", action="store_true", help="one message per project to Telegram")
    a = ap.parse_args()
    for pj in common.load_projects(a.projects):
        res = scan_project(pj, a.days, a.all)
        if a.telegram:
            common.send(message(pj, res))
            continue
        print(f"=== {pj['name']}")
        if res["error"]:
            print(res["error"])
            continue
        print(f"media files: {len(res['files'])} · names in account: {res.get('known', 0)}")
        if res["account_error"]:
            print("ACCOUNT NOT READ — no 'already uploaded' check was made:", res["account_error"])
        for u in res["unread"][:10]:
            print("NOT READ:", u)
        for r in res["rows"]:
            print("%-4s %-11s %7.1f MB  %s" % ("NEW" if r["new"] else "—", human_age(r["mtime"]),
                                              r["size"] / 1e6, r["rel"]))
        groups = by_folder(res["rows"])
        print(f"\nnot uploaded: {sum(len(v) for v in groups.values())} of {len(res['files'])}")
        for folder, items in groups.items():
            print(f"  {folder:<42} {len(items)}")


if __name__ == "__main__":
    main()
