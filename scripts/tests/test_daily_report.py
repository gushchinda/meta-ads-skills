import importlib.util, os, pathlib, tempfile
spec = importlib.util.spec_from_file_location(
    "daily_report",
    pathlib.Path(__file__).resolve().parent.parent / "daily_report.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_report_kind_from_config_flags():
    # install kind when extra_metrics has installs
    assert mod.report_kind({"extra_metrics": {"installs": "omni_app_install"}}, {}) == "install"
    # purchase_roas when config opts into roas
    assert mod.report_kind({"report_kind": "purchase_roas"}, {}) == "purchase_roas"
    # subscribe when conversion action is subscribe
    assert mod.report_kind({"conversion_action": "subscribe"}, {}) == "subscribe"
    # default purchase
    assert mod.report_kind({}, {}) == "purchase"


def test_resolve_range_explicit_date():
    since, until, label = mod.resolve_range("2026-06-15")
    assert since == "2026-06-15" and until == "2026-06-15"


def test_resolve_range_7d_returns_english_label():
    since, until, label = mod.resolve_range("7d")
    assert "days" in label.lower()  # no Russian strings


def test_list_projects_skips_adjust_and_example_configs():
    with tempfile.TemporaryDirectory() as tmp:
        for fname in ("example.yaml", "subs-app.yaml", "adjust.yaml", "adjust.example.yaml"):
            open(os.path.join(tmp, fname), "w").close()
        assert mod.list_projects(tmp) == ["example", "subs-app"]


def test_adjust_campaign_data_returns_disabled_tuple_when_config_missing():
    # reports/adjust.yaml doesn't exist in this repo checkout by default —
    # the call must degrade gracefully instead of raising FileNotFoundError.
    result = mod.adjust_campaign_data("AcmeApp", "2026-01-01", "2026-01-01")
    assert result == (None, None)
