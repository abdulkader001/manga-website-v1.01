"""Lightweight JSON configuration management for the FastAPI backend.

``save_config``/``update_config`` currently have no callers anywhere in the
application — only ``load_config`` is used, by
``app/api/routers/management.py``'s ``GET /config``. That endpoint therefore
always returns ``{}`` in real deployments, since nothing ever writes
``admin_config.json``. Not to be confused with the unrelated ``ConfigManager``
class in ``app/scrapers/config.py``, whose own ``save_config`` persists
scraper selector definitions to the ``Setting`` table and has real callers.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

DEFAULT_CONFIG_PATH = Path("admin_config.json")
CONFIG_PATH = DEFAULT_CONFIG_PATH


def _get_config_path() -> Path:
    override = os.getenv("ADMIN_CONFIG_PATH")
    if override:
        return Path(override)
    return DEFAULT_CONFIG_PATH


def load_config() -> Dict[str, Any]:
    config_path = _get_config_path()
    if not config_path.exists():
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[config_manager] Failed to load config: {exc}")
        return {}


def save_config(data: Dict[str, Any]) -> None:
    try:
        config_path = _get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(config_path.parent))
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
            json.dump(data, tmp_file, indent=2, ensure_ascii=False)
        os.replace(tmp_path, config_path)
    except OSError as exc:  # pragma: no cover - file system errors vary
        raise RuntimeError(f"[config_manager] Failed to save config: {exc}") from exc


def update_config(updates: Dict[str, Any]) -> Dict[str, Any]:
    data = load_config()
    data.update(updates)
    save_config(data)
    return data


__all__ = [
    "CONFIG_PATH",
    "DEFAULT_CONFIG_PATH",
    "load_config",
    "save_config",
    "update_config",
]
