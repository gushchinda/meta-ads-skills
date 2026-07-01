import pytest
from pathlib import Path

from deploy_creatives.client_config import load_client_config, ClientConfig

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_client_config_fields():
    config = load_client_config(FIXTURES / "example.yaml")
    assert config.name == "AcmeApp"
    assert config.product == "AcmeApp - Example Subscription App"
    assert config.ad_account_id == "act_123456789"
    assert config.facebook_page_id == "111111111111111"
    assert config.instagram_actor_id == "222222222222222"
    assert config.pixel_id == "333333333333333"
    assert config.currency == "USD"


def test_load_client_config_creatives_root():
    config = load_client_config(FIXTURES / "example.yaml")
    assert config.creatives_root == Path("examples/media/example")


def test_load_client_config_campaign_defaults():
    config = load_client_config(FIXTURES / "example.yaml")
    assert config.campaign_defaults["objective"] == "OUTCOME_SALES"
    assert config.campaign_defaults["bid_strategy"] == "LOWEST_COST_WITHOUT_CAP"


def test_load_client_config_adset_defaults():
    config = load_client_config(FIXTURES / "example.yaml")
    assert config.adset_defaults["daily_budget"] == 2000
    assert config.adset_defaults["optimization_goal"] == "OFFSITE_CONVERSIONS"
    targeting = config.adset_defaults["targeting"]
    assert targeting["age_min"] == 18
    assert "US" in targeting["geo_locations"]["countries"]


def test_load_client_config_destination():
    config = load_client_config(FIXTURES / "example.yaml")
    assert config.destination["type"] == "WEBSITE"
    assert config.destination["url"] == "https://example.com"
    assert config.destination["cta"] == "DOWNLOAD"


def test_load_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_client_config(Path("/nonexistent/client.yaml"))


def test_load_missing_required_field_raises():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "bad.yaml"
        p.write_text("name: Test\n")
        with pytest.raises(ValueError, match="ad_account_id"):
            load_client_config(p)


def test_resolve_client_by_name():
    from deploy_creatives.client_config import resolve_client_config
    config = resolve_client_config("example", clients_dir=FIXTURES)
    assert config.name == "AcmeApp"


def test_resolve_client_not_found():
    from deploy_creatives.client_config import resolve_client_config
    with pytest.raises(FileNotFoundError, match="no_such_client"):
        resolve_client_config("no_such_client", clients_dir=FIXTURES)
