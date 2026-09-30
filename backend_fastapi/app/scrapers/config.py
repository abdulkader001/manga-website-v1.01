import json
from typing import Dict, Any, Optional
from ..core.db import SessionLocal
from ..models import Setting


class ConfigManager:
    @classmethod
    def get_config(cls, domain: str) -> Optional[Dict[str, Any]]:
        """
        Fetch the dynamic configuration for a specific domain.
        Returns None if not found.
        """
        key = f"scraper_config_{domain}"
        session = SessionLocal()
        try:
            setting = session.query(Setting).filter(Setting.key == key).first()
            if setting and setting.value:
                return json.loads(setting.value)

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
