"""Page images that a reader page keeps inside a ``<script>`` instead of
``<img>`` tags.

Many Chinese manga sites run one of a few shared CMSes, and each hides the
chapter's image list in a script that JavaScript turns into ``<img>`` tags
after the page loads. Fetching the HTML therefore finds no images at all.
These decoders read the list straight out of the script. Pure Python, no
JavaScript is executed.

* ``sinmh``  -- ``var chapterImages = [...]; var chapterPath = "...";``
* ``qtcms``  -- ``var qTcms_S_m_murl_e = "<base64>";`` (URLs joined by
  ``$qingtiandy$``)
* ``packed`` -- a Dean-Edwards ``eval(function(p,a,c,k,e,d){...})`` script,
  unpacked and then searched like any other script
* ``script_array`` -- any JSON-style array of image URLs in a script

``auto_images`` tries them all, most specific first. Every result is a list
of absolute URLs in reading order; an empty list means "not found here".
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Iterable, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import packed_scripts, parsing

_IMAGE_EXT = re.compile(r"\.(?:jpe?g|png|webp|gif|avif|bmp)$", re.I)
_NOISE = re.compile(r"logo|avatar|icon|banner|sprite|emoji|button|badge|loading|/ads?/|advert", re.I)

# Upper bound on how much script text is scanned per page (huge inline
# bundles are not where an image list lives, and regexes on megabytes of
# minified JS waste worker time).
MAX_SCRIPT_CHARS = 400_000

_STD_PACKED = re.compile(
    r"\}\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'((?:[^'\\]|\\.)*)'\s*\.split\(\s*'\|'\s*\)",
    re.S,
)


def _scripts(soup: BeautifulSoup) -> List[str]:
    bodies: List[str] = []
    total = 0
    finder = getattr(soup, "find_all", None)
    if not callable(finder):
        return bodies
    for script in finder("script"):
        if script.get("src"):
            continue
        body = script.string or script.get_text() or ""
        if not body.strip():
            continue
        total += len(body)
        if total > MAX_SCRIPT_CHARS:
            break
        bodies.append(body)
    return bodies


def unpack_standard(script: str) -> Optional[str]:
    """Plain text of a standard (non-LZString) Dean-Edwards packed script."""

    match = _STD_PACKED.search(script)
    if not match:
        return None
    payload = match.group(1).replace("\\'", "'").replace("\\\\", "\\")
    base, count = int(match.group(2)), int(match.group(3))
    if not 2 <= base <= 62 or count > 20000:
        return None
    return packed_scripts.unpack_packer(payload, base, count, match.group(4).split("|"))


def _expanded_scripts(soup: BeautifulSoup) -> List[str]:
    """Every inline script, plus the unpacked text of packed ones."""

    out: List[str] = []
    for body in _scripts(soup):
        out.append(body)
        if "function(p,a,c,k,e,d)" in body.replace(" ", ""):
            plain = unpack_standard(body)
            if plain:
                out.append(plain)
    return out


def _js_string_array(text: str, start: int) -> Optional[List[str]]:
    """The array literal starting at ``text[start] == '['`` when it is a list
    of plain strings (single or double quoted)."""

    depth, i, quote = 0, start, ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                literal = text[start : i + 1]
                break
        i += 1
    else:
        return None
    if depth != 0:
        return None
    try:
        value = json.loads(literal)
    except ValueError:
        try:  # single-quoted JS strings
            value = json.loads(re.sub(r"'((?:[^'\\]|\\.)*)'", lambda m: json.dumps(m.group(1)), literal))
        except ValueError:
            return None
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        return [v.replace("\\/", "/") for v in value]
    return None


def _js_string(text: str, name: str) -> Optional[str]:
    match = re.search(r"\b" + re.escape(name) + r"\s*=\s*([\"'])((?:\\.|(?!\1).)*)\1", text)
    return match.group(2).replace("\\/", "/") if match else None


def _absolute(page_url: str, value: str, prefix: str = "") -> Optional[str]:
    value = value.strip()
    if not value:
        return None
    if value.startswith("//"):
        value = (urlparse(page_url).scheme or "https") + ":" + value
    if not re.match(r"https?://", value, re.I) and prefix:
        value = prefix.rstrip("/") + "/" + value.lstrip("/")
    return parsing.absolute(page_url, value)


def _clean(urls: Iterable[Optional[str]]) -> List[str]:
    return parsing.dedupe(u for u in urls if u and not _NOISE.search(u))


def sinmh_images(soup: BeautifulSoup, page_url: str) -> List[str]:
    """SinMH CMS: ``chapterImages`` (+ ``chapterPath`` and the resource host)."""

    for body in _expanded_scripts(soup):
        position = body.find("chapterImages")
        if position < 0:
            continue
        bracket = body.find("[", position)
        files = _js_string_array(body, bracket) if bracket >= 0 else None
        if not files:
            continue
        path = _js_string(body, "chapterPath") or ""
        host = ""
        for text in _expanded_scripts(soup):
            found = re.search(r"\"domain\"\s*:\s*\[\s*\"([^\"]+)\"", text) or re.search(
                r"\b(?:resHost|imgHost|pageImage)\s*=\s*[\"'](https?://[^\"']+)[\"']", text
            )
            if found:
                host = found.group(1)
                break
        base = page_url
        if host:
            base = host if host.startswith("http") else "https://" + host.lstrip("/")
        prefix = urljoin(base.rstrip("/") + "/", path.lstrip("/")) if path else (host or "")
        return _clean(_absolute(page_url, f, prefix) for f in files)
    return []


def qtcms_images(soup: BeautifulSoup, page_url: str) -> List[str]:
    """qTcms CMS: base64 list in ``qTcms_S_m_murl_e`` split on ``$qingtiandy$``."""

    for body in _scripts(soup):
        encoded = _js_string(body, "qTcms_S_m_murl_e")
        if not encoded:
            continue
        try:
            decoded = base64.b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8", "replace")
        except (binascii.Error, ValueError):
            continue
        host = _js_string(body, "qTcms_m_weburl") or ""
        return _clean(_absolute(page_url, part, host) for part in decoded.split("$qingtiandy$"))
    return []


def script_array_images(soup: BeautifulSoup, page_url: str) -> List[str]:
    """The longest array of image URLs found in any script (≥2 entries)."""

    best: List[str] = []
    for body in _expanded_scripts(soup):
        for match in re.finditer(r"\[\s*[\"']", body):
            values = _js_string_array(body, match.start())
            if not values or len(values) < 2:
                continue
            images = [v for v in values if _IMAGE_EXT.search(v.split("#")[0].split("?")[0])]
            if len(images) < max(2, int(len(values) * 0.8)):
                continue
            urls = _clean(_absolute(page_url, v) for v in images)
            if len(urls) > len(best):
                best = urls
    return best


DECODERS = {
    "sinmh": sinmh_images,
    "qtcms": qtcms_images,
    "script_array": script_array_images,
}


def auto_images(soup: BeautifulSoup, page_url: str) -> List[str]:
    """First decoder that finds images, most specific first."""

    for decoder in (sinmh_images, qtcms_images, script_array_images):
        found = decoder(soup, page_url)
        if found:
            return found
    return []


def decode(name: str, soup: BeautifulSoup, page_url: str) -> List[str]:
    if name == "auto_script":
        return auto_images(soup, page_url)
    decoder = DECODERS.get(name)
    return decoder(soup, page_url) if decoder else []
