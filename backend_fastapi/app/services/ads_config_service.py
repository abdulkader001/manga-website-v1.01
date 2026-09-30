"""Advertisement configuration helpers for the FastAPI backend."""

from __future__ import annotations

import json
import structlog
from dataclasses import dataclass
from typing import Any, Dict, List

from ..core.db import SessionLocal
from ..models import Setting

logger = structlog.get_logger(__name__)

SETTING_KEY = "ads_config"


@dataclass
class AdSlotConfig:
    """Simple structure representing a single ad network slot."""

    network: str = ""
    api_url: str = ""

    @classmethod
    def from_payload(cls, payload: object) -> "AdSlotConfig":
        if not isinstance(payload, dict):
            return cls()
        network = (
            payload.get("network") if isinstance(payload.get("network"), str) else ""
        )
        api_url = (
            payload.get("api_url") if isinstance(payload.get("api_url"), str) else ""
        )
        return cls(network=network.strip(), api_url=api_url.strip())

    def to_dict(self) -> Dict[str, str]:
        return {"network": self.network, "api_url": self.api_url}


DEFAULT_ADS_CONFIG: Dict[str, Any] = {
    "global": AdSlotConfig().to_dict(),
    "header_rows": [AdSlotConfig().to_dict(), AdSlotConfig().to_dict()],
    "footer_rows": [AdSlotConfig().to_dict(), AdSlotConfig().to_dict()],
}


def _normalise_row(entries: object, expected_length: int = 2) -> List[Dict[str, str]]:
    normalised: List[Dict[str, str]] = []
    if isinstance(entries, list):
        for entry in entries[:expected_length]:
            normalised.append(AdSlotConfig.from_payload(entry).to_dict())

    while len(normalised) < expected_length:
        normalised.append(AdSlotConfig().to_dict())

    return normalised


def normalise_ads_config(payload: object) -> Dict[str, Any]:
    """Normalise arbitrary payload data into a strict ``ads_config`` mapping."""

    config = dict(DEFAULT_ADS_CONFIG)

    if isinstance(payload, dict):
        config["global"] = AdSlotConfig.from_payload(payload.get("global")).to_dict()
        config["header_rows"] = _normalise_row(payload.get("header_rows"))
        config["footer_rows"] = _normalise_row(payload.get("footer_rows"))

    return config


def load_ads_config() -> Dict[str, Any]:
    """Load the ads configuration from the database, falling back to defaults."""

    session = SessionLocal()
    try:
        setting = session.query(Setting).filter(Setting.key == SETTING_KEY).first()
        if not setting or not setting.value:
            return dict(DEFAULT_ADS_CONFIG)

        try:
            data = json.loads(setting.value)
        except Exception:  # pragma: no cover - defensive for invalid JSON
            logger.warning(
                "Invalid ads_config payload stored; falling back to defaults."
            )
            return dict(DEFAULT_ADS_CONFIG)
    finally:
        session.close()

    return normalise_ads_config(data)


def save_ads_config(payload: object) -> Dict[str, Any]:
    """Persist the ads configuration to the database after normalisation."""

    config = normalise_ads_config(payload)
    serialized = json.dumps(config)

    session = SessionLocal()
    try:
        setting = session.query(Setting).filter(Setting.key == SETTING_KEY).first()
        if setting:
            setting.value = serialized
        else:
            session.add(Setting(key=SETTING_KEY, value=serialized))
        session.commit()
    finally:
        session.close()

    return config


__all__ = [
    "AdSlotConfig",
    "DEFAULT_ADS_CONFIG",
    "load_ads_config",
    "normalise_ads_config",
    "save_ads_config",
]
