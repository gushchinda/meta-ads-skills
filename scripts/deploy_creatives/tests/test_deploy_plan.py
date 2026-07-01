import pytest
from pathlib import Path

from deploy_creatives.client_config import load_client_config
from deploy_creatives.media_scanner import MediaFiles
from deploy_creatives.deploy_plan import build_deploy_plan, render_preview, DeployPlan

FIXTURES = Path(__file__).parent / "fixtures"


def _make_config():
    return load_client_config(FIXTURES / "example.yaml")


def _make_media():
    return MediaFiles(all_files=[
        Path("/fake/bunker_1080x1920.mp4"),
        Path("/fake/bunker_1080x1080.mp4"),
        Path("/fake/bunker_screenshot.png"),
    ])


def _make_texts():
    return {
        "bodies": [
            "Looking for parenting content? Download now!",
            "Want to unlock your child's potential?",
        ],
        "titles": [
            "27 Friends Use This App",
            "Transform Your Child's Learning",
        ],
    }


def test_build_deploy_plan_fields():
    config = _make_config()
    media = _make_media()
    texts = _make_texts()
    plan = build_deploy_plan(
        config=config,
        concept_name="bunker",
        media=media,
        texts=texts,
    )
    assert plan.ad_account_id == "act_123456789"
    assert plan.concept_name == "bunker"
    assert plan.facebook_page_id == "111111111111111"
    assert plan.instagram_actor_id == "222222222222222"
    assert plan.pixel_id == "333333333333333"
    assert plan.campaign_objective == "OUTCOME_SALES"
    assert plan.bid_strategy == "LOWEST_COST_WITHOUT_CAP"
    assert plan.daily_budget == 2000
    assert plan.optimization_goal == "OFFSITE_CONVERSIONS"
    assert plan.destination_url is not None
    assert plan.cta == "DOWNLOAD"


def test_build_deploy_plan_ads():
    config = _make_config()
    media = _make_media()
    texts = _make_texts()
    plan = build_deploy_plan(config=config, concept_name="bunker", media=media, texts=texts)
    assert len(plan.ads) == 3
    assert plan.ads[0]["name"] == "bunker_1080x1920"
    assert plan.ads[0]["file"] == Path("/fake/bunker_1080x1920.mp4")
    assert plan.ads[1]["name"] == "bunker_1080x1080"
    assert plan.ads[2]["name"] == "bunker_screenshot"


def test_build_deploy_plan_texts():
    config = _make_config()
    media = _make_media()
    texts = _make_texts()
    plan = build_deploy_plan(config=config, concept_name="bunker", media=media, texts=texts)
    assert len(plan.bodies) == 2
    assert len(plan.titles) == 2
    assert "parenting" in plan.bodies[0]


def test_build_deploy_plan_targeting():
    config = _make_config()
    media = _make_media()
    texts = _make_texts()
    plan = build_deploy_plan(config=config, concept_name="bunker", media=media, texts=texts)
    assert plan.targeting["age_min"] == 18
    assert "US" in plan.targeting["geo_locations"]["countries"]


def test_render_preview_contains_key_info():
    config = _make_config()
    media = _make_media()
    texts = _make_texts()
    plan = build_deploy_plan(config=config, concept_name="bunker", media=media, texts=texts)
    preview = render_preview(plan)
    assert "bunker" in preview
    assert "act_123456789" in preview
    assert "bunker_1080x1920" in preview
    assert "bunker_screenshot" in preview
    assert "Looking for parenting" in preview
    assert "27 Friends" in preview
    assert "DOWNLOAD" in preview
    assert "OUTCOME_SALES" in preview


def test_render_preview_shows_file_per_ad():
    config = _make_config()
    media = _make_media()
    texts = _make_texts()
    plan = build_deploy_plan(config=config, concept_name="bunker", media=media, texts=texts)
    preview = render_preview(plan)
    assert "bunker_1080x1920.mp4" in preview
    assert "bunker_screenshot.png" in preview
