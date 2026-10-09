"""Shared plumbing for the UA-ops skills (creative-monitor, creative-testing,
test-adset-stop, budget-scaling): .env, Meta Graph API, project config,
JSON state and Telegram delivery.

Nothing here touches the network at import time, so the decision logic in the
other modules can be unit-tested without a token.
"""
import copy
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

GRAPH = "https://graph.facebook.com/" + os.environ.get("META_GRAPH_VERSION", "v21.0")

# Configs and state live in the directory you run the scripts from (your ops
# repo), not inside the plugin — same convention as `reports/` for /report.
RULES_DIR = Path(os.environ.get("UA_RULES_DIR", "rules"))
STATE_DIR = Path(os.environ.get("UA_STATE_DIR", "run"))

DEFAULTS = {
    "name": None,
    "currency": "USD",
    "accounts": [],
    # Predicted LTV of one paying user, in account currency. Every money rule
    # is derived from it; a project without LTV is reported, never acted on.
    "ltv": None,
    "conversion_event": "purchase",
    "lead_event": "lead",
    "roas_multiplier": 1.0,
    "campaign_match": [],
    "creatives": {
        "dir": None,
        "include": [],
        "exclude": ["_archive", "_wip", "_static", "_raw"],
        "withdrawn": [],
    },
    "testing": {
        "campaign_prefix": "TEST",
        "campaign_id": None,
        "template_adset_id": None,
        "daily_budget": 50,
        "status": "ACTIVE",
        "page_id": None,
        "instagram_user_id": None,
        "link": None,
        "link_caption": None,
        "cta": "LEARN_MORE",
        "title": None,
        "message": None,
        "url_tags": None,
    },
    "stop_rule": {
        "enabled": True,
        "campaign_prefix": "TEST",
        "alpha": 0.05,
        "p_max": 0.20,
        "roas_target": 1.0,
        "min_spend_cpa_mult": 2,
        "lead_spend_threshold": 100,
    },
    "rotation": {
        "enabled": False,          # True = pulse.py launches queued folders into free slots
        "max_slots": 5,
        "test_days": 7,
        "test_cap": None,          # lifetime spend per test; None = ltv × cap_ltv_mult
        "cap_ltv_mult": 5,
        "weekly_guide": None,      # informational weekly TEST spend guide
        "hold": [],
        "geo": None,
    },
    "scaling": {
        "enabled": True,
        "campaign_prefix": "SCALING",
        "window_days": 7,
        "lag_days": 1,
        "pivot": 1.0,
        "step_up": 0.15,
        "step_down": 0.15,
        "min_budget": 5,
        "max_budget": None,
    },
}


# --- env / token ----------------------------------------------------------

def load_env(path=".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_TOKEN = None


def token():
    """Raw Meta access token: META_ACCESS_TOKEN, else exchange PIPEBOARD_API_TOKEN."""
    global _TOKEN
    if _TOKEN:
        return _TOKEN
    load_env()
    tok = os.environ.get("META_ACCESS_TOKEN")
    if not tok:
        pk = os.environ.get("PIPEBOARD_API_TOKEN")
        if not pk:
            sys.exit("Set META_ACCESS_TOKEN or PIPEBOARD_API_TOKEN in .env")
        url = "https://pipeboard.co/api/meta/token?api_token=" + urllib.parse.quote(pk)
        tok = json.load(urllib.request.urlopen(url, timeout=60))["access_token"]
    _TOKEN = tok
    return tok


# --- Graph API ------------------------------------------------------------

class GraphError(RuntimeError):
    pass


def get(path, **params):
    """GET with pagination. Lists come back as a flat list, objects as a dict."""
    params["access_token"] = token()
    url = f"{GRAPH}/{path}?" + urllib.parse.urlencode(params)
    out = []
    while url:
        try:
            d = json.load(urllib.request.urlopen(url, timeout=180))
        except urllib.error.HTTPError as e:
            raise GraphError(f"GET {path}: {e.read().decode('utf-8', 'replace')[:300]}") from None
        if "data" not in d:
            return d
        out += d["data"]
        url = d.get("paging", {}).get("next")
    return out


def post(path, fields):
    """Form POST. Non-string values are JSON-encoded. Errors come back as {"error": ...}."""
    data = {k: v if isinstance(v, str) else json.dumps(v) for k, v in fields.items()}
    data["access_token"] = token()
    req = urllib.request.Request(f"{GRAPH}/{path}", data=urllib.parse.urlencode(data).encode())
    try:
        return json.load(urllib.request.urlopen(req, timeout=300))
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode("utf-8", "replace")[:300]}


def upload_file(path, fields, file_field, file_path, timeout=1800):
    """Multipart upload via curl (videos are too big for a form POST).

    The file path is quoted on purpose: for curl a comma in `-F name=@a,b`
    separates a LIST of files, so a folder like `Cats, Dogs` would silently
    upload nothing.
    """
    args = ["curl", "-s", "--max-time", str(timeout), "-X", "POST", f"{GRAPH}/{path}"]
    for k, v in fields.items():
        args += ["-F", "%s=%s" % (k, v if isinstance(v, str) else json.dumps(v))]
    args += ["-F", '%s=@"%s"' % (file_field, file_path), "-F", "access_token=" + token()]
    raw = subprocess.run(args, capture_output=True, text=True).stdout
    try:
        return json.loads(raw)
    except ValueError:
        return {"error": raw[:300] or "empty response from curl"}


def act_val(row, key):
    """Count of one action type in an insights row (actions or conversions)."""
    for field in ("actions", "conversions"):
        for a in row.get(field, []) or []:
            if a.get("action_type") == key:
                return int(float(a["value"]))
    return 0


# --- project config -------------------------------------------------------

def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def project_from_dict(key, raw):
    pj = _merge(DEFAULTS, raw)
    pj["key"] = key
    pj["name"] = pj["name"] or key
    pj["accounts"] = [a["id"] if isinstance(a, dict) else a for a in pj["accounts"]]
    if pj["ltv"] is not None:
        pj["ltv"] = float(pj["ltv"])
        if pj["ltv"] <= 0:
            raise ValueError(f"{key}: ltv must be positive")
    r = pj["stop_rule"]
    if not 0 < r["alpha"] < 1 or not 0 < r["p_max"] <= 1:
        raise ValueError(f"{key}: stop_rule.alpha must be in (0,1), p_max in (0,1]")
    return pj


def load_project(key):
    path = RULES_DIR / f"{key}.yaml"
    if not path.exists():
        sys.exit(f"no config {path} — copy examples/rules/example.yaml there")
    return project_from_dict(key, yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def load_projects(keys=None):
    keys = keys or sorted(p.stem for p in RULES_DIR.glob("*.yaml"))
    if not keys:
        sys.exit(f"no project configs in {RULES_DIR}/ — copy examples/rules/example.yaml")
    return [load_project(k) for k in keys]


def matches(pj, name):
    """Campaign belongs to the project (only matters when accounts are shared)."""
    m = pj["campaign_match"]
    return not m or any(s.lower() in name.lower() for s in m)


def has_prefix(name, prefix):
    return name.strip().upper().startswith(prefix.upper()) if prefix else True


def money(pj, v):
    sym = {"USD": "$", "EUR": "€", "GBP": "£"}.get(pj["currency"], pj["currency"] + " ")
    return f"{sym}{v:,.2f}"


# --- state ----------------------------------------------------------------

def load_state(name):
    try:
        return json.loads((STATE_DIR / name).read_text(encoding="utf-8"))
    except Exception:
        # Missing or broken state means "I did nothing yet", never "refuse to act".
        return {}


def save_state(name, data):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_DIR / (name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, STATE_DIR / name)


# --- Telegram -------------------------------------------------------------

def send(text):
    """Send HTML text to Telegram if configured; otherwise print it."""
    load_env()
    bot, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (bot and chat):
        print(text)
        return None
    payload = {"chat_id": chat, "text": text, "parse_mode": "HTML",
               "disable_web_page_preview": True}
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"})
    return json.load(urllib.request.urlopen(req, timeout=60))
