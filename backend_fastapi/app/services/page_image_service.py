"""Chapter page images: download once, compress, store in ONE lightweight format.

Every page of a chapter is fetched from the source through the SSRF-safe
client, decoded with Pillow (decompression-bomb safe), and re-encoded as WebP:

* one format for everything the site serves (JPEG/PNG/GIF/AVIF/... sources all
  become WebP), which every browser, CDN and image host handles;
* width capped (``PAGE_MAX_WIDTH``, default 1280px) -- wide enough for OCR to
  read small lettering, and small enough that AI-vision models (which shrink
  anything much bigger) still see the text at close to full detail;
* quality chosen per image against a bytes-per-pixel budget, but never below a
  floor that keeps text edges clean: blocky/ringing artefacts around lettering
  hurt OCR and make erasing the original text look dirty. Flat or screentone-
  free art is stored losslessly, which is exact for text;
* very tall webtoon strips are cut into slices of at most 3000px (WebP cannot
  exceed 16383px, and huge canvases hurt phones and vision models); cuts are
  made on the most uniform row near the limit so speech bubbles and text are
  not split;
* the stored file is the one canonical picture: the reader displays it and OCR
  reads it, so detected text coordinates line up exactly with what is shown;
* metadata stripped, transparency flattened onto white, EXIF rotation applied.

Files are content-addressed (``NNNN-<sha1[:10]>.webp``) so they can be cached
forever by browsers and CDNs. A page that cannot be fetched or decoded keeps
its source URL, so a chapter is never left empty because one image failed.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import structlog
from PIL import Image, ImageOps, ImageStat

from ..utils.image_safety import ImageTooLargeError, InvalidImageError, open_image_safely

logger = structlog.get_logger(__name__)

PAGE_URL_PREFIX = os.getenv("PUBLIC_API_PREFIX", "/api/v1").rstrip("/") + "/manga/pages/"

MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_SOURCE_PIXELS = 80_000_000
MAX_SLICE_HEIGHT = 3000
CUT_SEARCH_WINDOW = 320
# Quality ladder tried in order until the slice fits its byte budget. The
# floor keeps text edges clean for OCR and for erasing the original lettering.
QUALITY_LADDER = (84, 78, 72)
BYTES_PER_PIXEL_BUDGET = 0.22
DOWNLOAD_WORKERS = 4
_FILENAME_RE = re.compile(r"^\d{4}-[a-f0-9]{10}\.webp$")


def max_width() -> int:
    try:
        return max(600, int(os.getenv("PAGE_MAX_WIDTH", "1280")))
    except ValueError:
        return 1280


def mirroring_enabled() -> bool:
    return os.getenv("MIRROR_PAGE_IMAGES", "true").strip().lower() not in {"0", "false", "no", "off"}


def pages_dir() -> Path:
    configured = os.getenv("PAGE_STORAGE_DIR")
    base = Path(configured) if configured else Path(__file__).resolve().parents[3] / "storage" / "pages"
    base.mkdir(parents=True, exist_ok=True)
    return base


def is_local_url(url: object) -> bool:
    return isinstance(url, str) and url.startswith(PAGE_URL_PREFIX)


def public_url(manga_id: int, chapter_id: int, filename: str) -> str:
    return f"{PAGE_URL_PREFIX}{int(manga_id)}/{int(chapter_id)}/{filename}"


def path_for(manga_id: int, chapter_id: int, filename: str) -> Optional[Path]:
    """Filesystem path of a stored page, or ``None`` when the name is not one
    this service wrote (blocks any path traversal)."""

    if not _FILENAME_RE.match(filename or ""):
        return None
    target = pages_dir() / str(int(manga_id)) / str(int(chapter_id)) / filename
    return target if target.is_file() else None


def path_from_url(url: str) -> Optional[Path]:
    """Filesystem path for one of our own page URLs."""

    if not is_local_url(url):
        return None
    parts = url[len(PAGE_URL_PREFIX):].split("?", 1)[0].split("/")
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    return path_for(int(parts[0]), int(parts[1]), parts[2])


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------


@dataclass
class EncodedPage:
    data: bytes
    width: int
    height: int


def _flatten(image: Image.Image) -> Image.Image:
    """RGB image, transparency flattened onto white, EXIF rotation applied."""

    image = ImageOps.exif_transpose(image)
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


def _quietest_row(image: Image.Image, target: int, floor: int) -> int:
    """Row in ``[floor, target]`` with the least variation (blank margin)."""

    best_row, best_score = target, None
    gray = image.convert("L")
    width = gray.width
    for row in range(target, max(floor, 1), -2):
        score = ImageStat.Stat(gray.crop((0, row, width, row + 1))).stddev[0]
        if best_score is None or score < best_score:
            best_row, best_score = row, score
            if score < 1.0:
                break
    return best_row


def _slices(image: Image.Image) -> List[Image.Image]:
    if image.height <= MAX_SLICE_HEIGHT:
        return [image]
    pieces, top = [], 0
    while image.height - top > MAX_SLICE_HEIGHT:
        target = top + MAX_SLICE_HEIGHT
        cut = _quietest_row(image, target, max(top + MAX_SLICE_HEIGHT - CUT_SEARCH_WINDOW, top + 1))
        pieces.append(image.crop((0, top, image.width, cut)))
        top = cut
    pieces.append(image.crop((0, top, image.width, image.height)))
    return pieces


FLAT_ART_MAX_COLORS = 8192


def _looks_like_flat_art(piece: Image.Image) -> bool:
    """Few distinct colours (flat/cel-shaded art, screentone-free pages):
    lossless WebP usually beats lossy on these, and is exact for text."""

    thumb = piece.copy()
    thumb.thumbnail((256, 256))
    colors = thumb.getcolors(maxcolors=FLAT_ART_MAX_COLORS + 1)
    return colors is not None and len(colors) <= FLAT_ART_MAX_COLORS


def _encode(piece: Image.Image) -> bytes:
    budget = piece.width * piece.height * BYTES_PER_PIXEL_BUDGET
    data = b""
    for quality in QUALITY_LADDER:
        buffer = io.BytesIO()
        piece.save(buffer, format="WEBP", quality=quality, method=4)
        data = buffer.getvalue()
        if len(data) <= budget:
            break
    if _looks_like_flat_art(piece):
        lossless = io.BytesIO()
        piece.save(lossless, format="WEBP", lossless=True, quality=80, method=4)
        if len(lossless.getvalue()) < len(data):
            return lossless.getvalue()
    return data


def compress_page(raw: bytes) -> List[EncodedPage]:
    """Decode ``raw`` (any raster format) and return one or more WebP slices.

    Raises :class:`InvalidImageError` / :class:`ImageTooLargeError` for data
    that is not a usable image.
    """

    image = open_image_safely(raw, max_pixels=MAX_SOURCE_PIXELS)
    image = _flatten(image)
    limit = max_width()
    if image.width > limit:
        height = max(1, round(image.height * limit / image.width))
        image = image.resize((limit, height), Image.LANCZOS)
    return [EncodedPage(_encode(piece), piece.width, piece.height) for piece in _slices(image)]


# ---------------------------------------------------------------------------
# Mirroring a chapter
# ---------------------------------------------------------------------------


@dataclass
class MirrorResult:
    urls: List[str]
    source_urls: List[str]
    stored_bytes: int = 0
    source_bytes: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def mirrored(self) -> bool:
        return self.failed < len(self.source_urls) and bool(self.source_urls)


def _download(url: str, referer: Optional[str], headers: Optional[Dict[str, str]]) -> bytes:
    from ..scrapers.http_client import RequestWrapper

    request_headers = {"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}
    request_headers.update(headers or {})
    if referer:
        request_headers["Referer"] = referer
    response = RequestWrapper.get(url, timeout=30, headers=request_headers, max_bytes=MAX_SOURCE_BYTES)
    if response.status_code != 200:
        raise ValueError(f"HTTP {response.status_code}")
    return response.content


def _fetch_and_compress(
    url: str, referer: Optional[str], headers: Optional[Dict[str, str]]
) -> Tuple[Optional[List[EncodedPage]], int, Optional[str]]:
    try:
        raw = _download(url, referer, headers)
        return compress_page(raw), len(raw), None
    except (InvalidImageError, ImageTooLargeError) as exc:
        return None, 0, f"not a usable image: {str(exc)[:80]}"
    except Exception as exc:  # network / SSRF guard / size cap
        return None, 0, str(exc)[:120]


def mirror_chapter(
    manga_id: int,
    chapter_id: int,
    source_urls: Sequence[str],
    *,
    referer: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> MirrorResult:
    """Download, compress and store every page. Failed pages keep their
    source URL; already-local URLs are left as they are."""

    sources = [u for u in source_urls if isinstance(u, str) and u]
    result = MirrorResult(urls=list(sources), source_urls=list(sources))
    remote = [(i, u) for i, u in enumerate(sources) if u.startswith(("http://", "https://"))]
    if not remote:
        return result

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        outcomes = list(pool.map(lambda item: _fetch_and_compress(item[1], referer, headers), remote))

    final = pages_dir() / str(int(manga_id)) / str(int(chapter_id))
    staging = final.with_name(f"{final.name}.tmp-{uuid.uuid4().hex[:8]}")
    staging.mkdir(parents=True, exist_ok=True)
    by_index: Dict[int, List[str]] = {}
    counter = 0
    try:
        for (index, url), (slices, size, error) in zip(remote, outcomes):
            if not slices:
                result.failed += 1
                result.errors.append(f"{url}: {error}")
                continue
            result.source_bytes += size
            names: List[str] = []
            for piece in slices:
                counter += 1
                name = f"{counter:04d}-{hashlib.sha1(piece.data).hexdigest()[:10]}.webp"
                (staging / name).write_bytes(piece.data)
                result.stored_bytes += len(piece.data)
                names.append(public_url(manga_id, chapter_id, name))
            by_index[index] = names
        if not by_index:
            return result  # nothing usable: leave the source URLs in place
        # Rebuild the ordered list: mirrored pages (possibly several slices)
        # or the untouched source URL for a page that failed.
        urls: List[str] = []
        for index, url in enumerate(sources):
            urls.extend(by_index.get(index, [url]))
        result.urls = urls
        if final.exists():
            shutil.rmtree(final, ignore_errors=True)
        staging.replace(final)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    logger.info(
        "chapter_pages_mirrored",
        manga_id=manga_id,
        chapter_id=chapter_id,
        pages=len(sources),
        failed=result.failed,
        source_kb=result.source_bytes // 1024,
        stored_kb=result.stored_bytes // 1024,
    )
    return result


def delete_chapter_files(manga_id: int, chapter_id: int) -> None:
    shutil.rmtree(pages_dir() / str(int(manga_id)) / str(int(chapter_id)), ignore_errors=True)


def delete_series_files(manga_id: int) -> None:
    shutil.rmtree(pages_dir() / str(int(manga_id)), ignore_errors=True)


def delete_all_files() -> None:
    base = pages_dir()
    for child in base.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def delete_page_file(url: str) -> None:
    path = path_from_url(url)
    if path is not None:
        path.unlink(missing_ok=True)


def referer_for_chapter(chapter_url: str) -> Tuple[Optional[str], Optional[Dict[str, str]]]:
    """Referer and extra headers a source's images expect, from its parser
    config; defaults to the chapter page itself, which is what a browser
    sends and what hotlink protection checks for."""

    from urllib.parse import urlparse

    from ..scrapers.config import ConfigManager

    domain = urlparse(chapter_url or "").netloc
    config = (ConfigManager.get_config(domain) or {}) if domain else {}
    referer: Optional[str] = chapter_url or None
    configured = config.get("image_referer")
    if isinstance(configured, str) and configured.startswith(("http://", "https://")):
        referer = configured
    extra = config.get("headers") if isinstance(config.get("headers"), dict) else None
    return referer, extra
