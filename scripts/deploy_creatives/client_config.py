from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

import yaml

REQUIRED_FIELDS = ["name", "ad_account_id", "facebook_page_id", "creatives_root",
                   "campaign_defaults", "adset_defaults", "destination"]


@dataclass
class ClientConfig:
    name: str
    ad_account_id: str
    facebook_page_id: str
    creatives_root: Path
    campaign_defaults: Dict[str, Any]
    adset_defaults: Dict[str, Any]
    destination: Dict[str, Any]
    product: str = ""
    account_name: str = ""
    currency: str = "USD"
    instagram_actor_id: str = ""
    pixel_id: str = ""


def load_client_config(path: Path) -> ClientConfig:
    if not path.exists():
        raise FileNotFoundError(f"Client config not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    for field_name in REQUIRED_FIELDS:
        if field_name not in data:
            raise ValueError(f"Missing required field: {field_name}")

    return ClientConfig(
        name=data["name"],
        ad_account_id=data["ad_account_id"],
        facebook_page_id=str(data["facebook_page_id"]),
        creatives_root=Path(data["creatives_root"]),
        campaign_defaults=data["campaign_defaults"],
        adset_defaults=data["adset_defaults"],
        destination=data["destination"],
        product=data.get("product", ""),
        account_name=data.get("account_name", ""),
        currency=data.get("currency", "USD"),
        instagram_actor_id=str(data.get("instagram_actor_id", "")),
        pixel_id=str(data.get("pixel_id", "")),
    )


def resolve_client_config(client_name: str, clients_dir: Path = None) -> ClientConfig:
    if clients_dir is None:
        clients_dir = Path(__file__).parent.parent / "clients"
    path = clients_dir / f"{client_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Client config not found: {client_name} (looked at {path})")
    return load_client_config(path)
