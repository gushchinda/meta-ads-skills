"""Unit tests for the UA-ops rules — pure logic only, no network or token."""
import datetime
import os
import pathlib
import sys

import pytest
import yaml

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))

import adset_stop as stop  # noqa: E402
import budget_scaling as scale  # noqa: E402
import creative_monitor as mon  # noqa: E402
import launch_tests as launch  # noqa: E402
from ua_rules import common  # noqa: E402

RULE = dict(common.DEFAULTS["stop_rule"])


# --- creative-monitor -----------------------------------------------------

def test_norm_strips_batch_number_case_and_separators():
    assert mon.norm("03_Sunset_v22.mp4") == mon.norm("sunset v22") == "sunsetv22"
    assert mon.norm("clip (1).mov") == "clip"


def test_make_already_one_way_containment():
    already = mon.make_already({mon.norm("hook 3"), mon.norm("brandx_trunk")})
    assert already(mon.norm("02_summer_hook_3.mp4"))   # renamed to a convention
    assert not already(mon.norm("01_BrandX.mp4"))             # brand name ≠ same creative


def test_make_already_short_names_exact_only():
    already = mon.make_already({"11", "abc"})
    assert already("11")
    assert not already(mon.norm("clip 11 blue"))


def test_human_age_by_calendar_day():
    now = datetime.datetime(2026, 10, 9, 9, 0)
    assert mon.human_age(datetime.datetime(2026, 10, 9, 1, 0).timestamp(), now) == "today"
    assert mon.human_age(datetime.datetime(2026, 10, 8, 23, 50).timestamp(), now) == "yesterday"
    assert mon.human_age(datetime.datetime(2026, 10, 4, 12, 0).timestamp(), now) == "5 d ago"


def test_scan_folder_respects_include_exclude(tmp_path):
    for p in ("Concept_A/a1.mp4", "Concept_A/notes.txt", "_archive/old.mp4", "B/b1.png"):
        f = tmp_path / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    files, unread = mon.scan_folder(str(tmp_path), [], ["_archive"])
    names = sorted(os.path.basename(f[0]) for f in files)
    assert names == ["a1.mp4", "b1.png"] and not unread
    files, _ = mon.scan_folder(str(tmp_path), ["concept"], [])
    assert [os.path.basename(f[0]) for f in files] == ["a1.mp4"]


# --- creative-testing -----------------------------------------------------

def test_adset_number_continues_numbering():
    assert launch.adset_number(["01. Hook", "02. Pain", "Other"]) == 3
    assert launch.adset_number([]) == 1


def test_with_geo_replaces_only_countries_and_does_not_mutate():
    src = {"age_min": 25, "geo_locations": {"countries": ["US"], "regions": [{"key": "1"}]}}
    tg = launch.with_geo(src, ["GB", "AU"])
    assert tg["geo_locations"] == {"countries": ["GB", "AU"]} and tg["age_min"] == 25
    assert src["geo_locations"]["countries"] == ["US"]


def test_creative_spec_omits_empty_texts():
    t = dict(common.DEFAULTS["testing"], page_id="1", link="https://x.test", cta="DOWNLOAD")
    v = launch.creative_spec(t, "clip", video_id="9", image_url="https://img")
    vd = v["object_story_spec"]["video_data"]
    assert "message" not in vd and "title" not in vd and "url_tags" not in v
    i = launch.creative_spec(dict(t, message="Hi", url_tags="a=b"), "pic", image_hash="h")
    assert i["object_story_spec"]["link_data"]["message"] == "Hi" and i["url_tags"] == "a=b"


# --- test-adset-stop ------------------------------------------------------

def test_pcdf_matches_closed_form():
    assert stop.pcdf(0, 3) == pytest.approx(2.718281828 ** -3)
    assert stop.pcdf(-1, 3) == 0 and stop.pcdf(5, 0) == 1


def test_k_of_inverts_pcdf():
    for n in range(5):
        assert stop.pcdf(n, stop.k_of(n, 0.05)) == pytest.approx(0.05, abs=1e-9)
    assert stop.k_of(0, 0.05) == pytest.approx(2.9957, abs=1e-3)   # −ln 0.05


def test_thresholds_example():
    t = stop.thresholds(40, RULE)
    assert t["cpa"] == 40 and t["s_min"] == 80 and t["s_lead"] == 100
    assert t["lead_mu"] == pytest.approx(12.5)
    assert stop.pcdf(t["lead_n"], 12.5) < 0.05 <= stop.pcdf(t["lead_n"] + 1, 12.5)


def test_lead_test_without_power_never_fires():
    # p_max 100%: at S_lead = 2×CPA a healthy adset expects only 2 leads,
    # P(0 leads) = 13.5% ≥ alpha → zero leads proves nothing.
    rule = dict(RULE, p_max=1.0, lead_spend_threshold=10)
    assert stop.thresholds(1000, rule)["lead_n"] is None
    d = stop.evaluate(spend=2500, purchases=3, leads=0, lead_done=False, ltv=1000, rule=rule)
    assert not d["tests"][0]["failed"]


def test_purchase_kill_spend_grows_with_purchases_and_has_floor():
    limits = [stop.purchase_kill_spend(40, RULE, n) for n in range(5)]
    assert limits == sorted(limits) and limits[0] >= 80


def test_evaluate_decisions():
    below = stop.evaluate(50, 0, 0, False, 40, RULE)
    assert below["below_min"] and not below["kill"]
    early = stop.evaluate(105, 0, 2, False, 40, RULE)       # few leads at the checkpoint
    assert early["kill"] and early["lead_checked"]
    healthy = stop.evaluate(105, 1, 30, False, 40, RULE)
    assert not healthy["kill"]
    late = stop.evaluate(130, 0, 30, True, 40, RULE)         # 0 purchases past ~3×CPA
    assert late["kill"] and not late["lead_checked"]


# --- budget-scaling -------------------------------------------------------

CFG = dict(common.DEFAULTS["scaling"], min_budget=5, max_budget=100)


def test_window_ends_lag_days_ago():
    since, until = scale.window(dict(CFG, window_days=7, lag_days=4), datetime.date(2026, 10, 9))
    assert (since, until) == (datetime.date(2026, 9, 29), datetime.date(2026, 10, 5))


def test_predicted_roas():
    assert scale.predicted_roas(100, 3, 40, 1.0) == pytest.approx(1.2)
    assert scale.predicted_roas(0, 3, 40) is None


def test_new_budget_steps_and_clamps():
    assert scale.new_budget(50, True, CFG) == 57.5
    assert scale.new_budget(50, False, CFG) == 42.5
    assert scale.new_budget(95, True, CFG) == 100
    assert scale.new_budget(5.5, False, CFG) == 5


def test_guard_one_move_per_day_and_detects_foreign_change():
    today = datetime.date(2026, 10, 9)
    state = {"x": {"date": "2026-10-09", "before": 5000, "after": 5750}}
    assert "no second move" in scale.guard(state, "x", 5750, today)
    assert "someone else" in scale.guard(state, "x", 6000, today)
    assert scale.guard(state, "x", 5750, datetime.date(2026, 10, 10)) is None
    assert scale.guard({}, "x", 5000, today) is None


# --- config ---------------------------------------------------------------

def test_example_config_loads_and_merges_defaults():
    raw = yaml.safe_load((SCRIPTS.parent / "examples" / "rules" / "example.yaml").read_text())
    pj = common.project_from_dict("acme", raw)
    assert pj["ltv"] == 40 and pj["accounts"] == ["act_XXXXXXXXXXXX"]
    assert pj["stop_rule"]["alpha"] == 0.05 and pj["scaling"]["max_budget"] == 500


def test_config_rejects_bad_values():
    with pytest.raises(ValueError):
        common.project_from_dict("x", {"ltv": -1})
    with pytest.raises(ValueError):
        common.project_from_dict("x", {"stop_rule": {"alpha": 1.5}})


def test_prefix_and_match():
    assert common.has_prefix(" test. Hooks 09.10", "TEST")
    assert not common.has_prefix("Scaling TEST", "TEST")
    assert common.matches({"campaign_match": []}, "anything")
    assert not common.matches({"campaign_match": ["acme"]}, "Other app")


# --- test-pulse -----------------------------------------------------------

import pulse  # noqa: E402


def _pj(**over):
    raw = {"name": "Acme", "accounts": ["act_1"], "ltv": 40,
           "rotation": {"max_slots": 3, "enabled": True}}
    raw.update(over)
    return common.project_from_dict("acme", raw)


def test_cap_and_daily():
    assert pulse.test_cap(_pj()) == 200 and pulse.daily_for(200, 7) == 28.57
    assert pulse.test_cap(_pj(rotation={"test_cap": 135})) == 135
    assert pulse.test_cap(_pj(ltv=None)) is None


def test_end_reason():
    assert pulse.end_reason("PAUSED", 10, 200, 1, 7) == "EARLY_STOP"
    assert pulse.end_reason("CAMPAIGN_PAUSED", 10, 200, 1, 7) == "EARLY_STOP"
    assert pulse.end_reason("ACTIVE", 200, 200, 3, 7) == "CAP"
    assert pulse.end_reason("ACTIVE", 50, 200, 7.0, 7) == "AGE"
    assert pulse.end_reason("IN_PROCESS", 0, 200, 0, 7) is None


def test_fifo_oldest_first_and_hold():
    q = {"b": {"first_seen": "2026-10-02"}, "a": {"first_seen": "2026-10-03"}, "c": {"first_seen": "2026-10-01"}}
    assert pulse.fifo(q, {"c"}) == ["b", "a"]


def test_run_project_rotation_end_to_end(monkeypatch, tmp_path):
    """Two managed tests (one stopped by the stop rule, one over cap), one legacy
    adset, three queued folders and 3 slots → 2 tests end; UGC + legacy keep
    2 slots, so exactly one folder launches — the oldest in the queue."""
    monkeypatch.setattr(common, "STATE_DIR", tmp_path)
    now = datetime.datetime(2026, 10, 9, 2, 0, tzinfo=datetime.timezone.utc)
    common.save_state("pulse-acme.json", {"tests": {
        "s1": {"name": "Hooks", "folder": "Hooks", "launched_at": "2026-10-06T02:00:00+00:00", "cap": 200, "days": 7, "status": "RUNNING"},
        "s2": {"name": "Pain", "folder": "Pain", "launched_at": "2026-10-03T02:00:00+00:00", "cap": 200, "days": 7, "status": "RUNNING"},
        "s3": {"name": "UGC", "folder": "UGC", "launched_at": "2026-10-08T02:00:00+00:00", "cap": 200, "days": 7, "status": "RUNNING"},
    }, "queue": {"Old": {"first_seen": "2026-10-01T00:00:00+00:00"}}})
    adsets = [dict(id="s1", name="01. Hooks", status="PAUSED", effective_status="PAUSED"),
              dict(id="s2", name="02. Pain", status="ACTIVE", effective_status="ACTIVE"),
              dict(id="s3", name="03. UGC", status="ACTIVE", effective_status="ACTIVE"),
              dict(id="L1", name="legacy", status="ACTIVE", effective_status="ACTIVE")]
    ins = {"s1": 90, "s2": 205, "s3": 20, "L1": 500}

    def get(path, **kw):
        if path.endswith("/campaigns"):
            return [dict(id="c1", name="TEST. Acme", effective_status="ACTIVE")]
        if path == "c1/adsets":
            return adsets
        if path == "c1/insights" and kw.get("level") == "adset":
            return [dict(adset_id=k, spend=str(v), actions=[{"action_type": "purchase", "value": "1"}]) for k, v in ins.items()]
        if path == "c1/insights" and kw.get("level") == "ad":
            return [dict(ad_id="a1", impressions="100")]
        if path == "c1/ads":
            return [dict(id="a1", adset_id="s3"), dict(id="a2", adset_id="s3")]
        if path == "c1/insights":
            return [dict(spend="321.5")]
        raise AssertionError(path)

    posts, launched = [], []
    monkeypatch.setattr(common, "get", get)
    monkeypatch.setattr(common, "post", lambda path, f: posts.append((path, f)) or {"success": True})
    monkeypatch.setattr(launch, "collect", lambda pj, f, m: {"Old": ["o.mp4"], "New1": ["n1.mp4", "n2.mp4"], "New2": ["x.mp4"]})

    def fake_launch(pj, groups, daily_budget=None, geo=None):
        launched.append((list(groups), daily_budget))
        return {g: "new-" + g for g in groups}

    monkeypatch.setattr(launch, "launch", fake_launch)
    pj = _pj()
    pj["creatives"]["dir"] = str(tmp_path)
    res = pulse.run_project(pj, dry=False, now=now)

    assert {(e["name"], e["reason"]) for e in res["ended"]} == {("Hooks", "EARLY_STOP"), ("Pain", "CAP")}
    assert posts == [("s2", {"status": "PAUSED"})]          # stop-rule pause is never repeated
    assert launched == [(["Old"], 28.57)]                   # FIFO, daily = cap / days
    assert res["slots"] == {"active": 3, "max": 3}
    html_text = pulse.html_page([res], now, False)
    assert "Test pulse" in html_text and "legacy" in html_text and "zero delivery: 1/2" in html_text
    (tmp_path / "pulse.html").write_text(html_text)
