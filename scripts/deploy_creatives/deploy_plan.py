from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from deploy_creatives.client_config import ClientConfig
from deploy_creatives.media_scanner import MediaFiles


@dataclass
class DeployPlan:
    # Account
    ad_account_id: str
    concept_name: str
    facebook_page_id: str
    instagram_actor_id: str
    pixel_id: str
    currency: str

    # Campaign
    campaign_objective: str
    buying_type: str
    bid_strategy: str
    daily_budget: int
    special_ad_categories: List[str]

    # AdSet
    optimization_goal: str
    billing_event: str
    targeting: Dict[str, Any]

    # Creative texts
    bodies: List[str]
    titles: List[str]

    # Destination
    destination_url: str
    cta: str

    # Ads (one per media file)
    ads: List[Dict[str, Any]] = field(default_factory=list)


def build_deploy_plan(
    config: ClientConfig,
    concept_name: str,
    media: MediaFiles,
    texts: Dict[str, List[str]],
) -> DeployPlan:
    ads = [
        {"name": f.stem, "file": f}
        for f in media.all_files
    ]

    campaign = config.campaign_defaults
    adset = config.adset_defaults
    dest = config.destination

    return DeployPlan(
        ad_account_id=config.ad_account_id,
        concept_name=concept_name,
        facebook_page_id=config.facebook_page_id,
        instagram_actor_id=config.instagram_actor_id,
        pixel_id=config.pixel_id,
        currency=config.currency,
        campaign_objective=campaign["objective"],
        buying_type=campaign["buying_type"],
        bid_strategy=campaign["bid_strategy"],
        daily_budget=adset["daily_budget"],
        special_ad_categories=campaign.get("special_ad_categories", []),
        optimization_goal=adset["optimization_goal"],
        billing_event=adset["billing_event"],
        targeting=adset["targeting"],
        bodies=texts["bodies"],
        titles=texts["titles"],
        destination_url=dest["url"],
        cta=dest["cta"],
        ads=ads,
    )


def render_preview(plan: DeployPlan) -> str:
    budget_display = plan.daily_budget / 100
    currency_symbol = "$" if plan.currency == "USD" else plan.currency

    lines = [
        f"Campaign: {plan.ad_account_id} — {plan.concept_name} ({plan.campaign_objective}, {plan.buying_type})",
        f"  Bid: {plan.bid_strategy}",
        f"  Budget: {currency_symbol}{budget_display:.0f}/day",
        "",
        f"  AdSet: {plan.concept_name}",
        f"    Optimization: {plan.optimization_goal}",
        f"    Targeting: {plan.targeting['age_min']}-{plan.targeting['age_max']}, "
        f"{len(plan.targeting['geo_locations']['countries'])} countries",
        "",
    ]

    for ad in plan.ads:
        lines.append(f"    Ad: {ad['name']}")
        lines.append(f"        File: {ad['file'].name}")

    lines.append("")
    lines.append("  Texts (asset_feed_spec):")
    lines.append("    Bodies:")
    for i, body in enumerate(plan.bodies, 1):
        lines.append(f"      {i}. \"{body}\"")
    lines.append("    Headlines:")
    for i, title in enumerate(plan.titles, 1):
        lines.append(f"      {i}. \"{title}\"")

    lines.append("")
    lines.append(f"  Destination: {plan.destination_url}")
    lines.append(f"  CTA: {plan.cta}")
    lines.append(f"  Pixel: {plan.pixel_id}")

    return "\n".join(lines)
