from pathlib import Path

from deploy_creatives.client_config import load_client_config
from deploy_creatives.media_scanner import scan_media
from deploy_creatives.deploy_plan import build_deploy_plan, render_preview

FIXTURES = Path(__file__).parent / "fixtures"


def test_full_pipeline():
    config = load_client_config(FIXTURES / "example.yaml")
    media = scan_media(FIXTURES / "sample_concept")
    texts = {
        "bodies": ["Test body text 1", "Test body text 2"],
        "titles": ["Test headline 1"],
    }

    plan = build_deploy_plan(
        config=config,
        concept_name="sample_concept",
        media=media,
        texts=texts,
    )

    assert plan.ad_account_id == "act_123456789"
    assert len(plan.ads) == 3
    assert plan.ads[0]["name"] == "001_Test_1x1"

    preview = render_preview(plan)
    assert "sample_concept" in preview
    assert "001_Test_1x1" in preview
    assert "Test body text 1" in preview
    assert "Test headline 1" in preview
    assert "DOWNLOAD" in preview
