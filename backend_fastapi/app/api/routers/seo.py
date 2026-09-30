"""Search-engine feeds served at the site root: sitemap.xml and rss.xml."""

from __future__ import annotations

from datetime import datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ...core.db import get_read_db
from ...core.settings import settings
from ...models import Chapter, Manga

router = APIRouter(tags=["seo"])

MAX_SITEMAP_URLS = 45000


def _base_url(request: Request) -> str:
    configured = (settings.frontend_url or "").rstrip("/")
    if configured:
        return configured
    return f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"


def _hostable(db: Session):
    return db.query(Manga).filter(
        Manga.may_host.is_(True), Manga.takedown_status == "none"
    )


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap(request: Request, db: Session = Depends(get_read_db)) -> Response:
    base = _base_url(request)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"  <url><loc>{escape(base)}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>",
        f"  <url><loc>{escape(base)}/browse</loc><changefreq>daily</changefreq><priority>0.9</priority></url>",
    ]
    count = 2
    for manga in _hostable(db).order_by(Manga.updated_at.desc().nullslast()).yield_per(500):
        if count >= MAX_SITEMAP_URLS:
            break
        lastmod = (manga.updated_at or manga.created_at or datetime.utcnow()).date().isoformat()
        parts.append(
            f"  <url><loc>{escape(base)}/manga/{manga.id}</loc><lastmod>{lastmod}</lastmod>"
            "<changefreq>weekly</changefreq><priority>0.8</priority></url>"
        )
        count += 1
    parts.append("</urlset>")
    return Response("\n".join(parts), media_type="application/xml")


@router.get("/rss.xml", include_in_schema=False)
@router.get("/feed.xml", include_in_schema=False)
def rss(request: Request, db: Session = Depends(get_read_db)) -> Response:
    base = _base_url(request)
    rows = (
        db.query(Chapter, Manga)
        .join(Manga, Manga.id == Chapter.manga_id)
        .filter(Manga.may_host.is_(True), Manga.takedown_status == "none")
        .filter(Chapter.ingestion_status == "complete")
        .order_by(Chapter.created_at.desc().nullslast(), Chapter.id.desc())
        .limit(50)
        .all()
    )
    items = []
    for chapter, manga in rows:
        number = chapter.chapter_number
        label = f"{manga.title} - Chapter {number.normalize() if hasattr(number, 'normalize') else number}"
        published = (chapter.created_at or chapter.scraped_at or datetime.utcnow()).strftime(
            "%a, %d %b %Y %H:%M:%S +0000"
        )
        link = f"{base}/reader/{manga.id}/{chapter.id}"
        items.append(
            "  <item>"
            f"<title>{escape(label)}</title>"
            f"<link>{escape(link)}</link>"
            f"<guid isPermaLink=\"true\">{escape(link)}</guid>"
            f"<pubDate>{published}</pubDate>"
            "</item>"
        )
    body = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>',
            "  <title>Latest chapter releases</title>",
            f"  <link>{escape(base)}</link>",
            "  <description>New manga, manhwa and manhua chapters.</description>",
            f'  <atom:link href="{escape(base)}/rss.xml" rel="self" type="application/rss+xml"/>',
            *items,
            "</channel></rss>",
        ]
    )
    return Response(body, media_type="application/rss+xml")
