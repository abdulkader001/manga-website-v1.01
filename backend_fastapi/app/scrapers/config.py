import json
from typing import Dict, Any, Optional
from ..core.db import SessionLocal
from ..models import Setting


class ConfigManager:
    @staticmethod
    def domain_candidates(domain: str) -> list[str]:
        """The host, then each parent domain down to two labels
        (``m.www.a.com`` -> ``m.www.a.com``, ``www.a.com``, ``a.com``), so a
        parser saved for the approved apex domain also serves its subdomains.
        """

        host = (domain or "").strip().lower().split(":")[0]
        labels = [label for label in host.split(".") if label]
        return [".".join(labels[i:]) for i in range(0, max(len(labels) - 1, 1))]

    @classmethod
    def get_config(cls, domain: str) -> Optional[Dict[str, Any]]:
        """
        Fetch the dynamic configuration for a specific domain.
        Returns None if not found.
        """
        session = SessionLocal()
        try:
            candidates = cls.domain_candidates(domain) or [domain]
            for candidate in candidates:
                setting = (
                    session.query(Setting)
                    .filter(Setting.key == f"scraper_config_{candidate}")
                    .first()
                )
                if setting and setting.value:
                    return json.loads(setting.value)

            # Built-in per-site parser (scrapers/presets.py) when the admin
            # has not stored or approved a version for this domain yet.
            from .presets import preset_for_domain

            preset = preset_for_domain(domain)
            if preset is not None:
                return preset

            # Default mock for known domains if they don't exist yet
            if domain == "example-manga.com":
                return {
                    "manga_title": "h1.manga-title",
                    "manga_description": "div.summary",
                    "manga_cover": "img.cover",
                    "chapter_list": "ul.chapters li",
                    "chapter_url": "a",
                    "chapter_title": "span.title",
                    "chapter_number": "span.number",
                    "page_images": "div.page-image img",
                }
            return None
        except Exception:
            return None
        finally:
            session.close()

    @classmethod
    def save_config(cls, domain: str, config: Dict[str, Any]):
        """
        Save the dynamic configuration (e.g. AI extracted selectors) to the database.
        """
        key = f"scraper_config_{domain}"
        session = SessionLocal()
        try:
            setting = session.query(Setting).filter(Setting.key == key).first()
            if not setting:
                setting = Setting(key=key, value=json.dumps(config))
                session.add(setting)
            else:
                setting.value = json.dumps(config)
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
