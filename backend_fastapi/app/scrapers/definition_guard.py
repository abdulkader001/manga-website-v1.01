"""Guardrails for parser definitions written by the Scraper AI.

An AI answer is untrusted input: it can be malformed, invent keys the engine
ignores, use selectors that do not compile, or (if the page it read carried a
prompt-injection) try to point the scraper at another host or attach
credentials. ``sanitize`` turns an answer into a definition the engine can
run safely, and reports every problem in plain words so the next AI attempt
can correct it.

Rules
-----
* Only keys the engine understands survive (``ALLOWED_KEYS``); each must have
  the right type.
* CSS selectors must compile, stay under ``MAX_SELECTOR_CHARS`` and avoid
  brittle position-based pseudo-classes.
* Any URL the scraper would *fetch* (chapter list APIs, image APIs, AJAX
  chapter lists) must stay on the page's own site (same registrable domain)
  and use http(s). Image CDNs are fine for image URLs, never for fetches.
* Request headers are limited to ``Accept``, ``Accept-Language`` and a
  same-site ``Referer``. Cookies, Authorization and anything else are dropped.
* ``decoder`` names must be ones the engine ships.

The result-level checks (``check_chapter_urls`` / ``check_page_images``) catch
a definition that "works" but extracts the wrong thing -- navigation links
instead of chapters, logos instead of pages.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

MAX_SELECTOR_CHARS = 400
MAX_TEMPLATE_CHARS = 500

SELECTOR_KEYS = (
    "manga_title",
    "manga_description",
    "manga_cover",
    "manga_author",
    "manga_genres",
    "chapter_list",
    "chapter_url",
    "chapter_title",
    "chapter_number",
    "chapter_list_next",
    "page_images",
    "next_page",
    "page_list",
    "hidden_chapter_list",
    "ajax_marker",
)
TEXT_KEYS = ("image_attr", "page_url_template", "encoding", "series_id_regex", "image_referer")
DICT_KEYS = ("image_source", "chapter_source", "chapter_api", "image_api", "chapter_ajax", "headers")
INT_KEYS = ("skip_first_images",)
ALLOWED_KEYS = set(SELECTOR_KEYS) | set(TEXT_KEYS) | set(DICT_KEYS) | set(INT_KEYS)

KNOWN_DECODERS = {"manhuagui", "sinmh", "qtcms", "script_array", "auto_script"}
ALLOWED_HEADERS = {"accept", "accept-language", "referer"}
ALLOWED_ENCODINGS = {"utf-8", "gbk", "gb2312", "gb18030", "big5", "shift_jis", "euc-jp", "euc-kr"}

_BRITTLE = re.compile(r":nth-(?:child|of-type|last-child|last-of-type)|^\s*html\b|^\s*body\s*>", re.I)
_ATTR_NAME = re.compile(r"^[A-Za-z][\w:-]{0,40}$")
_MULTI_PART_SUFFIXES = {"co.kr", "co.jp", "or.jp", "ne.jp", "com.cn", "net.cn", "com.tw", "co.uk", "com.br"}
_NOISE_IMAGE = re.compile(r"logo|avatar|icon|banner|sprite|emoji|button|badge|/ads?/|advert|placeholder|loading", re.I)


def site_of(host: str) -> str:
    """Registrable domain, roughly: ``img.cdn.example.co.kr`` -> ``example.co.kr``."""

    labels = [part for part in (host or "").lower().strip(".").split(".") if part]
    if len(labels) <= 2:
        return ".".join(labels)
    if ".".join(labels[-2:]) in _MULTI_PART_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def same_site(url: str, page_url: str) -> bool:
    """``url`` (possibly relative or a ``{template}``) stays on ``page_url``'s site."""

    url = (url or "").strip()
    if not url:
        return False
    if url.startswith("{url}") or url.startswith("{base}") or url.startswith("{stem}"):
        return True
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if not parsed.scheme and not parsed.netloc:
        return True  # relative: resolved against the page itself
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname or ""
    page_host = urlparse(page_url or "").hostname or ""
    return bool(host) and bool(page_host) and site_of(host) == site_of(page_host)


def selector_problem(selector: Any) -> Optional[str]:
    """Why ``selector`` is unusable, or ``None`` when it is fine."""

    if not isinstance(selector, str) or not selector.strip():
        return "is empty"
    if len(selector) > MAX_SELECTOR_CHARS:
        return f"is longer than {MAX_SELECTOR_CHARS} characters"
    if _BRITTLE.search(selector):
        return "uses a position-based or absolute path (:nth-child / html > ...), which breaks on the next chapter"
    try:
        import soupsieve

        soupsieve.compile(selector)
    except Exception as exc:  # soupsieve.SelectorSyntaxError and friends
        return f"is not valid CSS ({str(exc).splitlines()[0][:120]})"
    return None


def _clean_headers(value: Any, page_url: str, problems: List[str]) -> Optional[Dict[str, str]]:
    if not isinstance(value, dict):
        problems.append("headers must be an object")
        return None
    clean: Dict[str, str] = {}
    for key, raw in value.items():
        name = str(key).strip()
        if name.lower() not in ALLOWED_HEADERS:
            problems.append(f"header {name!r} is not allowed (only Accept, Accept-Language, Referer)")
            continue
        if not isinstance(raw, str) or "\n" in raw or "\r" in raw or len(raw) > 300:
            problems.append(f"header {name!r} has an invalid value")
            continue
        if name.lower() == "referer" and page_url and not same_site(raw, page_url):
            problems.append("Referer must be a page on the same site")
            continue
        clean[name] = raw
    return clean or None


def _clean_fetch_spec(name: str, value: Any, page_url: str, problems: List[str]) -> Optional[Dict[str, Any]]:
    """chapter_api / image_api / chapter_ajax: a URL the scraper will fetch."""

    if isinstance(value, str) and name == "chapter_ajax" and value == "madara":
        return {"kind": "madara"}
    if not isinstance(value, dict):
        problems.append(f"{name} must be an object")
        return None
    spec = dict(value)
    if name == "chapter_ajax" and spec.get("kind") == "madara":
        return {"kind": "madara"}
    url = spec.get("url")
    if not isinstance(url, str) or not url.strip() or len(url) > MAX_TEMPLATE_CHARS:
        problems.append(f"{name}.url is missing or too long")
        return None
    if page_url and not same_site(url, page_url):
        problems.append(f"{name}.url must stay on the same website as the page (got {url[:80]!r})")
        return None
    method = str(spec.get("method") or "GET").upper()
    if method not in ("GET", "POST"):
        problems.append(f"{name}.method must be GET or POST")
        return None
    spec["method"] = method
    template = spec.get("url_template")
    if template is not None and (not isinstance(template, str) or len(template) > MAX_TEMPLATE_CHARS):
        problems.append(f"{name}.url_template is invalid")
        spec.pop("url_template", None)
    if "params_regex" in spec:
        try:
            re.compile(str(spec["params_regex"]))
        except re.error:
            problems.append(f"{name}.params_regex is not a valid regular expression")
            return None
    if "data" in spec and not isinstance(spec["data"], dict):
        spec.pop("data")
    return spec


def _clean_source(name: str, value: Any, problems: List[str]) -> Optional[Dict[str, Any]]:
    """image_source / chapter_source: data read from the already-fetched page."""

    if isinstance(value, str) and value in KNOWN_DECODERS:
        return {"decoder": value}
    if not isinstance(value, dict):
        problems.append(f"{name} must be an object")
        return None
    spec = dict(value)
    decoder = spec.get("decoder")
    if decoder is not None and decoder not in KNOWN_DECODERS:
        problems.append(f"{name}.decoder {decoder!r} is unknown (use one of {sorted(KNOWN_DECODERS)})")
        return None
    if decoder is None and not (spec.get("marker") or spec.get("script_selector")):
        problems.append(f"{name} needs a decoder, a marker or a script_selector")
        return None
    if spec.get("script_selector") and selector_problem(spec["script_selector"]):
        problems.append(f"{name}.script_selector {selector_problem(spec['script_selector'])}")
        return None
    host = spec.get("host")
    if host is not None and not (isinstance(host, str) and re.match(r"https?://", host)):
        spec.pop("host")
    return spec


def sanitize(definition: Any, page_url: str = "") -> Tuple[Dict[str, Any], List[str]]:
    """``(clean_definition, problems)``. ``problems`` is empty when the answer
    was accepted unchanged."""

    problems: List[str] = []
    if not isinstance(definition, dict):
        return {}, ["the answer was not a JSON object"]
    clean: Dict[str, Any] = {}
    for key, value in definition.items():
        if key not in ALLOWED_KEYS:
            problems.append(f"unknown key {key!r} was ignored")
            continue
        if value is None or value == "":
            continue
        if key in SELECTOR_KEYS:
            problem = selector_problem(value)
            if problem:
                problems.append(f"{key} {value!r} {problem}")
                continue
            clean[key] = value.strip()
        elif key == "image_attr":
            if isinstance(value, str) and _ATTR_NAME.match(value):
                clean[key] = value
            else:
                problems.append("image_attr must be an attribute name such as data-src")
        elif key == "encoding":
            if isinstance(value, str) and value.lower() in ALLOWED_ENCODINGS:
                clean[key] = value.lower()
            else:
                problems.append(f"encoding must be one of {sorted(ALLOWED_ENCODINGS)}")
        elif key == "image_referer":
            if value == "page" or (isinstance(value, str) and page_url and same_site(value, page_url)):
                clean[key] = value
            else:
                problems.append('image_referer must be "page" or a URL on the same site')
        elif key == "series_id_regex":
            try:
                re.compile(str(value))
                clean[key] = str(value)
            except re.error:
                problems.append("series_id_regex is not a valid regular expression")
        elif key == "page_url_template":
            if isinstance(value, str) and "{n}" in value and len(value) <= MAX_TEMPLATE_CHARS and (
                not page_url or same_site(value, page_url)
            ):
                clean[key] = value
            else:
                problems.append("page_url_template must contain {n} and stay on the same site")
        elif key == "headers":
            headers = _clean_headers(value, page_url, problems)
            if headers:
                clean[key] = headers
        elif key in ("chapter_api", "image_api", "chapter_ajax"):
            spec = _clean_fetch_spec(key, value, page_url, problems)
            if spec:
                clean[key] = spec
        elif key in ("image_source", "chapter_source"):
            spec = _clean_source(key, value, problems)
            if spec:
                clean[key] = spec
        elif key == "skip_first_images":
            try:
                number = int(value)
            except (TypeError, ValueError):
                number = -1
            if 0 <= number <= 10:
                clean[key] = number
            else:
                problems.append("skip_first_images must be a number from 0 to 10")
    return clean, problems


def check_chapter_urls(urls: List[str], page_url: str) -> Optional[str]:
    """Why a list of extracted chapter links is not a real chapter list."""

    if not urls:
        return "no chapter links were found"
    distinct = set(urls)
    if page_url:
        distinct.discard(page_url)
        on_site = [u for u in distinct if same_site(u, page_url)]
        if distinct and len(on_site) < len(distinct) * 0.5:
            return "most chapter links point to other websites (probably ads or navigation)"
    if not distinct:
        return "every chapter link points back to the series page itself"
    if len(urls) >= 6 and len(distinct) <= 1:
        return "every chapter entry has the same link"
    return None


def check_page_images(urls: List[str]) -> Optional[str]:
    """Why a list of extracted page images is not a real chapter."""

    if not urls:
        return "no page images were found"
    noisy = [u for u in urls if _NOISE_IMAGE.search(u)]
    if len(noisy) == len(urls):
        return "every image looks like a logo, icon, banner or placeholder, not a manga page"
    return None
