#!/usr/bin/env python3
"""Daily Meta Ads report -> Telegram, via direct Graph API (Pipeboard/Meta token).
Runs locally (no meta-ads MCP needed).

Usage:
    python daily_report.py <project> [yesterday|7d|30d|YYYY-MM-DD] [--print]
    python daily_report.py [yesterday|7d|30d|YYYY-MM-DD] [--print]   # all projects

Projects are discovered from reports/*.yaml (adjust.yaml is config, not a project).
Secrets come from .env: META_ACCESS_TOKEN or PIPEBOARD_API_TOKEN,
TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, ADJUST_API_TOKEN.
Default date = yesterday (UTC)."""
import json, os, re, sys, time, datetime, urllib.parse, urllib.request, urllib.error
import yaml

def _open_retry(req, timeout=90):
    """urlopen with retry on transient 429/5xx (Meta & Adjust both flake intermittently)."""
    for i in range(4):
        try:
            return urllib.request.urlopen(req, timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < 3: time.sleep(3 * (i + 1)); continue
            raise
        except Exception:
            if i < 3: time.sleep(3); continue
            raise

try:  # python.org build lacks the system CA bundle — use certifi when available
    import ssl, certifi
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
except ImportError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GV = "v22.0"
NW_DEFAULT = 24          # name column width for 3-col projects
NW_NARROW = 21           # narrower for 4-col (ROAS) projects

def load_env():
    env = os.path.join(ROOT, ".env")
    if os.path.exists(env):
        for line in open(env):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

def http_get(url):
    return json.loads(_open_retry(url, 60).decode())

def get_token():
    """Raw Meta access token: prefer META_ACCESS_TOKEN, else exchange PIPEBOARD_API_TOKEN."""
    load_env()
    tok = os.environ.get("META_ACCESS_TOKEN")
    if tok:
        return tok
    pk = os.environ.get("PIPEBOARD_API_TOKEN")
    if not pk:
        sys.exit("Set META_ACCESS_TOKEN or PIPEBOARD_API_TOKEN in .env")
    return http_get(f"https://pipeboard.co/api/meta/token?api_token={pk}")["access_token"]

def get_tg_token():
    load_env()
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not tok:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set (.env)")
    return tok

def get_chat_id():
    load_env()
    cid = os.environ.get("TELEGRAM_CHAT_ID")
    if not cid:
        raise RuntimeError("TELEGRAM_CHAT_ID not set (.env)")
    return cid

def list_projects(reports_dir=None):
    d = reports_dir or os.path.join(ROOT, "reports")
    if not os.path.isdir(d):
        return []
    return sorted(f[:-5] for f in os.listdir(d)
                  if f.endswith(".yaml") and f != "adjust.yaml"
                  and not f.endswith(".example.yaml"))

def report_kind(cfg, acct):
    """install | subscribe | purchase | purchase_roas — from config, never project name."""
    if "installs" in (cfg.get("extra_metrics") or {}):
        return "install"
    if cfg.get("report_kind"):
        return cfg["report_kind"]
    caction = acct.get("conversion_action", cfg.get("conversion_action", "purchase"))
    if caction == "subscribe":
        return "subscribe"
    return "purchase"

def insights(tok, acct, since, until):
    rows, after = [], ""
    while True:
        q = {"level": "adset", "fields": "adset_id,campaign_name,adset_name,spend,actions,action_values,conversions",
             "time_range": json.dumps({"since": since, "until": until}), "limit": "200", "access_token": tok}
        if after: q["after"] = after
        data = http_get(f"https://graph.facebook.com/{GV}/{acct}/insights?{urllib.parse.urlencode(q)}")
        rows += data.get("data", [])
        after = data.get("paging", {}).get("cursors", {}).get("after", "")
        if not data.get("paging", {}).get("next"): break
    return rows

def active_adsets(tok, acct):
    """Adset ids currently delivering (effective_status ACTIVE)."""
    q = {"fields": "id", "effective_status": json.dumps(["ACTIVE"]), "limit": "500", "access_token": tok}
    d = http_get(f"https://graph.facebook.com/{GV}/{acct}/adsets?{urllib.parse.urlencode(q)}").get("data", [])
    return {a["id"] for a in d}

IAP_SHARE = 0.70   # IAP Revenue Mode = 70% Gross (store takes 30%); ad revenue counted 100% (MAX SDK)

def adjust_campaign_data(project, since, until):
    """Adjust Report Service per campaign. Revenue = ad_revenue + IAP(revenue)×0.70.
    ROAS = adj_revenue / cost (Meta: 'cost'; AppLovin: 'network_cost'). roas_d3 likewise on d3.
    Returns (map, m2_multipliers) or (None, None). map[key] = {roas,roas_d3,partner,cost,installs,rev,rev_d3,name}."""
    path = os.path.join(ROOT, "reports", "adjust.yaml")
    if not os.path.exists(path):
        return None, None
    cfg = yaml.safe_load(open(path))
    pj = (cfg.get("projects") or {}).get(project)
    if not pj: return None, None
    load_env()
    tok_val = os.environ.get("ADJUST_API_TOKEN") or (cfg.get("tokens", {}).get(pj["token"]))
    if not tok_val:
        return None, None
    q = urllib.parse.urlencode({
        "date_period": f"{since}:{until}",
        "app_token__in": ",".join(pj["app_tokens"]),
        "dimensions": "partner_name,campaign_network",
        "metrics": "cost,network_cost,installs,ad_revenue,revenue,ad_revenue_total_d3,revenue_total_d3"})
    req = urllib.request.Request(cfg["api_url"] + "?" + q,
        headers={"Authorization": "Bearer " + tok_val})
    rows = json.loads(_open_retry(req, 120).decode()).get("rows", [])
    divs = pj.get("ad_revenue_divisor", {})   # rough fix: API ad_revenue not filtered to MAX SDK source
    amap = {}
    for r in rows:
        f = lambda k: float(r.get(k) or 0)
        partner = r.get("partner_name") or ""
        div = divs.get(partner, 1) or 1
        cost = f("cost") or f("network_cost")    # Meta has 'cost'; AppLovin only 'network_cost'
        if cost <= 0: continue
        rev = f("ad_revenue") / div + f("revenue") * IAP_SHARE
        rev_d3 = f("ad_revenue_total_d3") / div + f("revenue_total_d3") * IAP_SHARE
        name = r.get("campaign_network") or ""
        amap[re.sub(r"\s*\(\d+\)\s*$", "", name).strip().lower()] = {
            "roas": rev / cost, "roas_d3": rev_d3 / cost, "partner": partner,
            "cost": cost, "installs": f("installs"), "rev": rev, "rev_d3": rev_d3, "name": name}
    return amap, pj.get("m2_multiplier", {})

def adjust_line(cname, adjust):
    """Per-campaign 'Adjust ROAS X%  Predict M2 Y%' line, or None."""
    if not adjust or not adjust[0]: return None
    amap, mult = adjust
    a = amap.get(cname.strip().lower())
    if not a or not (a["roas"] or a["roas_d3"]): return None
    m = mult.get(a["partner"]) or mult.get("Facebook") or 1.0
    return " " * 6 + f"Adjust D3 ROAS {a['roas_d3']*100:.0f}%  Predict M2 {a['roas_d3']*100*m:.0f}%"

def applovin_section(L, adjust):
    """AppLovin section from the shared Adjust map. spend=network_cost, revenue=ad_revenue+IAP×0.70."""
    amap, mult = adjust if adjust else (None, None)
    if not amap: return
    al = [v for v in amap.values() if v["partner"] == "Applovin" and v["cost"] > 0]
    if not al: return
    m = (mult or {}).get("Applovin", 2.53)
    L.append("=== APPLOVIN === (spend=network_cost, IAP×0.70, ad_rev÷2 ~MAX SDK)")
    tc = ti = trev = trev3 = 0.0
    for v in sorted(al, key=lambda x: -x["cost"]):
        c = v["cost"]; i = v["installs"]; tc += c; ti += i; trev += v["rev"]; trev3 += v["rev_d3"]
        L.append(re.sub(r"\s*\(\d+\)\s*$", "", v["name"]).strip()[:46])
        L.append(f"  €{c:,.0f}  {int(i)} inst" + (f"  CPI €{c/i:.2f}" if i else ""))
        L.append(f"  D3 ROAS {v['roas_d3']*100:.0f}%  Predict M2 {v['roas_d3']*100*m:.0f}%")
    if tc:
        L.append(f"AppLovin TOTAL: €{tc:,.0f} | {int(ti)} inst | D3 ROAS {trev3/tc*100:.0f}% | Predict M2 {trev3/tc*100*m:.0f}%")

def aval(arr, t):
    for a in (arr or []):
        if a.get("action_type") == t: return float(a["value"])
    return 0.0

def conv(row, caction):
    v = aval(row.get("actions"), caction)
    if v: return v
    if caction == "subscribe":
        for t in ("subscribe_total", "subscribe_website"):
            v = aval(row.get("conversions"), t)
            if v: return v
    return 0.0

def money(v, c): return c + f"{v:.2f}"
def pct(v): return "n/a" if v is None else f"{round(v)}%"
def trunc(s, w): return s if len(s) <= w else s[:w-1] + "…"

def row_line(nw, indent, name, cells):
    line = (" " * indent + trunc(name, nw - indent)).ljust(nw)
    for val, w in cells: line += str(val).rjust(w)
    return line.rstrip()

def build_account(lines, nw, acct_label, rows, caction, cur, kind, extra_total, active_ids=frozenset(), adjust=None):
    """kind: 'purchase'/'purchase_roas'(cv+CPA[+ROAS]) | 'subscribe'(sub+CPA) | 'install'(inst+CPI)
    adset names prefixed (A)=active / (P)=paused via active_ids."""
    rows = [r for r in rows if float(r.get("spend", 0)) > 0]
    if not rows:
        lines.append(f"{acct_label}: no spend"); return
    # group by campaign
    camps = {}
    for r in rows:
        camps.setdefault(r.get("campaign_name", "—"), []).append(r)
    def agg(rs):
        sp = sum(float(r["spend"]) for r in rs)
        cv = sum(conv(r, caction) for r in rs)
        rev = sum(aval(r.get("action_values"), caction) for r in rs)
        inst = sum(aval(r.get("actions"), "omni_app_install") for r in rs)
        leads = sum(aval(r.get("actions"), "lead") for r in rs)
        return sp, cv, rev, inst, leads
    asp, acv, arev, ainst, aleads = agg(rows)
    def cells(sp, cv, rev, inst):
        if kind == "install":
            return [(money(sp, cur), 8), (int(inst), 5), (money(sp/inst, cur) if inst else "—", 8)]
        if kind == "subscribe":
            return [(money(sp, cur), 8), (int(cv), 4), (money(sp/cv, cur) if cv else "—", 8)]
        base = [(money(sp, cur), 8), (int(cv), 4), (money(sp/cv, cur) if cv else "—", 8)]
        if kind == "purchase_roas":
            base.append((pct(rev/sp*100 if sp else None) if rev else "0%", 5))
        return base
    lines.append(row_line(nw, 0, acct_label, cells(asp, acv, arev, ainst)))
    for cname in sorted(camps, key=lambda c: -sum(float(r["spend"]) for r in camps[c])):
        rs = camps[cname]; csp, ccv, crev, cinst, _ = agg(rs)
        lines.append(row_line(nw, 2, "▸ " + cname[:8], cells(csp, ccv, crev, cinst)))
        aline = adjust_line(cname, adjust)
        if aline: lines.append(aline)
        for r in sorted(rs, key=lambda x: -float(x["spend"])):
            sp = float(r["spend"]); cv = conv(r, caction); rev = aval(r.get("action_values"), caction)
            inst = aval(r.get("actions"), "omni_app_install")
            nm = re.sub(r"[\s.]*\d{1,2}\.\d{1,2}\.\d{2,4}\s*$", "", r.get("adset_name", "—")).strip() or r.get("adset_name", "—")
            mark = "(A) " if r.get("adset_id") in active_ids else "(P) "
            lines.append(row_line(nw, 6, mark + nm, cells(sp, cv, rev, inst)))
    if extra_total is not None:
        extra_total[0] += aleads

def send_telegram(text):
    tg = get_tg_token()
    chat_id = get_chat_id()
    # split into <=4000 char chunks on line boundaries
    chunks, cur = [], ""
    for ln in text.split("\n"):
        if len(cur) + len(ln) + 1 > 3900:
            chunks.append(cur); cur = ""
        cur += ln + "\n"
    if cur.strip(): chunks.append(cur)
    for ch in chunks:
        # monospace code block so columns align on mobile; inside ``` only ` and \ are special (report has neither)
        body = urllib.parse.urlencode({"chat_id": chat_id, "text": "```\n" + ch + "\n```", "parse_mode": "MarkdownV2"}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{tg}/sendMessage", data=body)
        r = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        if not r.get("ok"): raise RuntimeError("tg send: " + json.dumps(r)[:200])

def resolve_range(arg):
    """arg: 'yesterday'|'7d'|'30d'|'YYYY-MM-DD' -> (since, until, label)."""
    today = datetime.datetime.now(datetime.UTC).date()
    y = today - datetime.timedelta(days=1)
    fmt = lambda d: d.strftime("%d.%m.%Y")
    if arg in ("7d", "7"):
        s = today - datetime.timedelta(days=7); return s.isoformat(), y.isoformat(), f"7 days ({s.strftime('%d.%m')}–{y.strftime('%d.%m')})"
    if arg in ("30d", "30"):
        s = today - datetime.timedelta(days=30); return s.isoformat(), y.isoformat(), f"30 days ({s.strftime('%d.%m')}–{y.strftime('%d.%m')})"
    if arg and re.match(r"\d{4}-\d{2}-\d{2}", arg):
        return arg, arg, fmt(datetime.date.fromisoformat(arg))
    return y.isoformat(), y.isoformat(), fmt(y)

def build_report_text(tok, since, until, label):
    L = [f"Daily Report — {label}", "(account ▸ campaign ▸ adset)", ""]
    calls = 0
    adjust_calls = [0]
    for proj in list_projects():
        cfg = yaml.safe_load(open(os.path.join(ROOT, "reports", proj + ".yaml")))
        cur = "€" if cfg.get("currency") == "EUR" else "$"
        L.append(f"=== {cfg['name']} ({cfg.get('currency','USD')}) ===")
        kind0 = report_kind(cfg, {})
        is_install = kind0 == "install"
        nw = NW_NARROW if cfg.get("narrow_table") else NW_DEFAULT
        hdr = (" " * nw + "spend".rjust(8) + ("inst".rjust(5) + "CPI".rjust(8) if is_install
               else "cv".rjust(4) + "CPA".rjust(8) + ("ROAS".rjust(5) if kind0 == "purchase_roas" else "")))
        L.append(hdr)
        leads_total = [0.0] if cfg.get("show_leads_total") else None
        adjust = adjust_campaign_data(proj, since, until) if cfg.get("adjust") else (None, None)
        if adjust[0] is not None: adjust_calls[0] += 1
        for acct in cfg["accounts"]:
            caction = acct.get("conversion_action", cfg.get("conversion_action", "purchase"))
            acct_label = f"{acct['name']} (…{acct['id'][-4:]})"
            rows = insights(tok, acct["id"], since, until); calls += 1
            active = active_adsets(tok, acct["id"]); calls += 1
            kind = report_kind(cfg, acct)
            build_account(L, nw, acct_label, rows, caction, cur, kind, leads_total, active, adjust)
        if cfg.get("roas_unavailable_note"):
            L.append("(ROAS n/a — no purchase value via API)")
        if cfg.get("show_leads_total") and leads_total:
            L.append(f"(leads: {int(leads_total[0])} total)")
        L.append("")
    L.append(f"Meta API: {calls} requests" + (f", Adjust API: {adjust_calls[0]}" if adjust_calls[0] else ""))
    return "\n".join(L)

def build_project_text(tok, proj, periods=None):
    """Single project, account ▸ campaign ▸ adset. periods = list of range keywords
    (default 3: yesterday/7d/30d); pass one for a single-window report."""
    cfg = yaml.safe_load(open(os.path.join(ROOT, "reports", proj + ".yaml")))
    cur = "€" if cfg.get("currency") == "EUR" else "$"
    kind0 = report_kind(cfg, {})
    is_install = kind0 == "install"
    nw = NW_NARROW if cfg.get("narrow_table") else NW_DEFAULT
    L = [f"{cfg['name']} — Report", "(account ▸ campaign ▸ adset)", ""]
    period_labels = {"yesterday": "Yesterday", "7d": "Last 7 days", "30d": "Last 30 days"}
    plist = [(period_labels.get(p, p), p) for p in (periods or ["yesterday", "7d", "30d"])]
    for plabel, arg in plist:
        since, until, lbl = resolve_range(arg)
        L.append(f"-- {plabel} ({lbl}) --")
        if cfg.get("show_applovin"): L.append("=== META ===")
        L.append(" " * nw + "spend".rjust(8) + ("inst".rjust(5) + "CPI".rjust(8) if is_install
                 else "cv".rjust(4) + "CPA".rjust(8) + ("ROAS".rjust(5) if kind0 == "purchase_roas" else "")))
        leads_total = [0.0] if cfg.get("show_leads_total") else None
        adjust = adjust_campaign_data(proj, since, until) if cfg.get("adjust") else (None, None)
        for acct in cfg["accounts"]:
            caction = acct.get("conversion_action", cfg.get("conversion_action", "purchase"))
            rows = insights(tok, acct["id"], since, until)
            active = active_adsets(tok, acct["id"])
            kind = report_kind(cfg, acct)
            build_account(L, nw, f"{acct['name']} (…{acct['id'][-4:]})", rows, caction, cur, kind, leads_total, active, adjust)
        if cfg.get("show_applovin"): applovin_section(L, adjust)
        L.append("")
    return "\n".join(L)

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    projects = list_projects()
    proj = next((a for a in args if a in projects), None)
    rng = next((a for a in args if a in ("yesterday", "7d", "7", "30d", "30") or re.match(r"\d{4}-\d{2}-\d{2}", a)), None)
    tok = get_token()
    if proj and rng:
        text = build_project_text(tok, proj, [rng])      # single project, one window
    elif proj:
        text = build_project_text(tok, proj)             # single project, 3 windows
    else:
        since, until, label = resolve_range(rng or "yesterday")
        text = build_report_text(tok, since, until, label)
    if "--print" in sys.argv:
        print(text)
    else:
        send_telegram(text)
        print("sent to Telegram")

if __name__ == "__main__":
    main()
