"""Backend behaviour the reader UI depends on: MangaUpdates metadata, parser
auto-detection for unknown / moved sites, signed image proxy, the
ratings / likes / reports / announcements endpoints and the import gate.

Every fixture here is synthetic; nothing touches the network.
"""

from __future__ import annotations

import uuid

import pytest
from bs4 import BeautifulSoup

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import Chapter, Manga, User, UserRole
from backend_fastapi.app.scrapers import autodetect, parsing, presets
from backend_fastapi.app.services import image_proxy, mangaupdates_service as mu


# --------------------------------------------------------------------------- MangaUpdates
def test_mangaupdates_id_is_base36_for_path_links_and_decimal_for_legacy():
    assert mu.series_id_from_url("https://www.mangaupdates.com/series/pi4azuo/solo-leveling") == int(
        "pi4azuo", 36
    )
    assert mu.series_id_from_url("https://www.mangaupdates.com/series.html?id=15180124") == 15180124


@pytest.mark.parametrize(
    "bad",
    ["https://evil.example/series/abc/x", "ftp://www.mangaupdates.com/series/abc/x", "https://www.mangaupdates.com/"],
)
def test_mangaupdates_rejects_foreign_or_id_less_links(bad):
    with pytest.raises(mu.MangaUpdatesError):
        mu.series_id_from_url(bad)


def test_mangaupdates_payload_maps_to_catalogue_fields():
    meta = mu.parse_series(
        {
            "series_id": 7,
            "title": "Dragon &amp; Test",
            "description": "Line one<br />Line two <b>bold</b>",
            "type": "Manhwa",
            "year": "2024",
            "image": {"url": {"original": "https://cdn.example/c.jpg"}},
            "genres": [{"genre": "Action"}, {"genre": "Action"}, {"genre": "Fantasy"}],
            "authors": [{"name": "A. Writer", "type": "Author"}, {"name": "B. Drawer", "type": "Artist"}],
            "associated": [{"title": "Alt Name"}],
            "status": "12 Chapters (Complete)",
            "completed": True,
        },
        "https://www.mangaupdates.com/series/7/x",
    )
    assert meta.title == "Dragon & Test"
    assert "<" not in meta.description and "Line two" in meta.description
    assert meta.genres == ["Action", "Fantasy"]
    assert meta.authors == ["A. Writer"] and meta.artists == ["B. Drawer"]
    assert meta.type == "manhwa" and meta.status == "completed"
    assert meta.cover_url == "https://cdn.example/c.jpg"


def test_mangaupdates_without_title_is_an_error_not_a_guess():
    with pytest.raises(mu.MangaUpdatesError):
        mu.parse_series({"series_id": 1}, "https://www.mangaupdates.com/series/1/x")


# --------------------------------------------------------------------------- parsing helpers
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Chapter 12", 12.0),
        ("Ch. 7.5 - The Fall", 7.5),
        ("第25话", 25.0),
        ("제 3 화", 3.0),
        ("Episode 40", 40.0),
    ],
)
def test_chapter_numbers_are_read_from_common_labels(text, expected):
    assert parsing.parse_chapter_number(text) == expected


def test_volume_numbers_are_never_mistaken_for_chapters():
    assert parsing.parse_chapter_number("Volume 3") is None


# --------------------------------------------------------------------------- auto-detection
def _series_page(css_class: str) -> str:
    items = "".join(
        f'<li class="{css_class}"><a href="/read/dragon/ch-{i}/">Chapter {i}</a></li>' for i in range(12, 0, -1)
    )
    return (
        "<html><head><meta property='og:image' content='https://x.example/c.png'></head><body>"
        "<nav><a href='/'>Home</a><a href='/latest'>Latest 2</a><a href='/top'>Top 10</a></nav>"
        f"<h1>Dragon</h1><ul>{items}</ul><footer><a href='/tos'>Terms</a></footer></body></html>"
    )


@pytest.mark.parametrize("css_class", ["chap-item", "wp-manga-chapter", "row-x"])
def test_chapter_list_is_found_without_knowing_the_site(css_class):
    definition = autodetect.detect_series_definition(_series_page(css_class), "https://new-domain.example/m/dragon/")
    assert definition and definition["manga_title"] == "h1"
    soup = BeautifulSoup(_series_page(css_class), "html.parser")
    matched = parsing.select(soup, definition["chapter_list"])
    assert len(matched) == 12, "selector must cover every chapter and nothing else"
    assert all("/read/dragon/" in a.get("href", "") or a.find("a") for a in matched)


def test_reader_images_are_found_through_lazy_loading_and_noise_is_ignored():
    html = (
        "<html><body><header><img src='/logo.png' width='90'></header>"
        + "".join(
            f"<div class='pg'><img data-src='https://cdn.example/{i}.jpg' src='data:image/gif;base64,R0lGOD'></div>"
            for i in range(1, 7)
        )
        + "<footer><img src='/banner-ads/x.png'></footer></body></html>"
    )
    definition = autodetect.detect_reader_definition(html, "https://new-domain.example/read/1")
    assert definition and definition.get("image_attr") == "data-src"
    soup = BeautifulSoup(html, "html.parser")
    assert len(parsing.select(soup, definition["page_images"])) == 6


def test_known_site_families_are_recognised_on_an_unknown_domain():
    html = (
        "<html><body><h1 class='entry-title'>T</h1><ul class='main version-chap'>"
        + "".join(
            f"<li class='wp-manga-chapter'><a href='/manga/t/chapter-{i}/'>Chapter {i}</a></li>"
            for i in range(1, 5)
        )
        + "</ul></body></html>"
    )
    assert presets.detect_family(html, "manga", pool=presets.known_definitions()) is not None


def test_sites_the_scraper_cannot_read_are_declared_not_faked():
    assert presets.unsupported_reason("tonarinoyj.jp")
    assert presets.unsupported_reason("www.comic-days.com")
    assert presets.unsupported_reason("rawkuma.com") is None


def test_preset_lookup_falls_back_to_parent_domain():
    assert presets.preset_for_domain("rawkuma.com")
    assert presets.preset_for_domain("cdn.rawkuma.com")
    assert presets.preset_for_domain("not-a-known-site.example") is None


# --------------------------------------------------------------------------- image proxy
def test_image_proxy_signature_rejects_tampering():
    link = image_proxy.proxied_url("https://img.example/a.jpg", "https://site.example/")
    query = dict(part.split("=", 1) for part in link.split("?", 1)[1].split("&"))
    assert image_proxy.decode_request(query["u"], query["r"], query["s"]) == (
        "https://img.example/a.jpg",
        "https://site.example/",
    )
    other = image_proxy._b64("http://169.254.169.254/latest/meta-data")
    assert image_proxy.decode_request(other, query["r"], query["s"]) is None
    assert image_proxy.decode_request(query["u"], query["r"], "0" * 40) is None
    assert image_proxy.decode_request("!!!", "!!!", "x") is None


# --------------------------------------------------------------------------- reader endpoints
def _user(role=UserRole.USER, **extra) -> tuple[dict, int]:
    session = SessionLocal()
    try:
        user = User(
            email=f"reader-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="Reader",
            role=role,
            provider="magic_link",
            **extra,
        )
        session.add(user)
        session.commit()
        return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}, user.id
    finally:
        session.close()


def _series_with_chapter() -> tuple[int, int]:
    session = SessionLocal()
    try:
        manga = Manga(title=f"Series {uuid.uuid4().hex[:6]}", source_url=f"https://s.example/{uuid.uuid4().hex}")
        session.add(manga)
        session.flush()
        chapter = Chapter(
            manga_id=manga.id,
            chapter_number=1,
            chapter_title="One",
            chapter_url=f"https://s.example/{uuid.uuid4().hex}/ch-1",
            pages=["https://i.example/1.jpg"],
        )
        session.add(chapter)
        session.commit()
        return manga.id, chapter.id
    finally:
        session.close()


def test_rating_is_one_per_reader_and_averaged(fastapi_client):
    manga_id, _ = _series_with_chapter()
    first, _ = _user()
    second, _ = _user()
    assert fastapi_client.post(f"/api/v1/manga/{manga_id}/rate", json={"rating": 8}, headers=first).status_code == 200
    fastapi_client.post(f"/api/v1/manga/{manga_id}/rate", json={"rating": 10}, headers=first)  # re-rate replaces
    body = fastapi_client.post(f"/api/v1/manga/{manga_id}/rate", json={"rating": 6}, headers=second).json()
    assert body["rating_count"] == 2 and body["rating"] == 8.0 and body["user_rating"] == 6
    assert fastapi_client.post(f"/api/v1/manga/{manga_id}/rate", json={"rating": 11}, headers=first).status_code == 422


def test_chapter_like_toggles(fastapi_client):
    _, chapter_id = _series_with_chapter()
    headers, _ = _user()
    assert fastapi_client.post(f"/api/v1/chapters/{chapter_id}/like", headers=headers).json()["liked"] is True
    again = fastapi_client.post(f"/api/v1/chapters/{chapter_id}/like", headers=headers).json()
    assert again["liked"] is False and again["likes"] == 0


def test_chapter_report_raises_a_staff_alert_until_an_admin_resolves_it(fastapi_client):
    _, chapter_id = _series_with_chapter()
    reader, _ = _user()
    admin, _ = _user(UserRole.ADMIN, is_main_admin=True, is_secondary_admin=True)
    sent = fastapi_client.post(
        f"/api/v1/chapters/{chapter_id}/report",
        json={"report_type": "Missing Images", "details": "page 3"},
        headers=reader,
    )
    assert sent.status_code in (200, 201)
    # Report status is staff-only: readers (and anonymous visitors) see nothing.
    assert fastapi_client.get(f"/api/v1/chapters/{chapter_id}/reports", headers=reader).json()["active_alert"] is None
    assert fastapi_client.get(f"/api/v1/chapters/{chapter_id}/reports").json()["active_alert"] is None
    alert = fastapi_client.get(f"/api/v1/chapters/{chapter_id}/reports", headers=admin).json()
    assert alert["active_alert"]["report_type"] == "Missing Images"
    report_id = sent.json()["report"]["id"]
    assert fastapi_client.post(f"/api/v1/reports/{report_id}/resolve", headers=reader).status_code in (401, 403)
    assert fastapi_client.post(f"/api/v1/reports/{report_id}/resolve", headers=admin).status_code == 200
    assert fastapi_client.get(f"/api/v1/chapters/{chapter_id}/reports", headers=admin).json()["active_alert"] is None


def test_only_admins_can_broadcast_announcements(fastapi_client):
    reader, _ = _user()
    admin, _ = _user(UserRole.ADMIN, is_main_admin=True, is_secondary_admin=True)
    payload = {"title": "Maintenance", "message": "Tonight", "type": "warning"}
    assert fastapi_client.post("/api/v1/admin/broadcast", json=payload, headers=reader).status_code in (401, 403)
    assert fastapi_client.post("/api/v1/admin/broadcast", json=payload, headers=admin).status_code in (200, 201)
    texts = [a["message"] for a in fastapi_client.get("/api/v1/announcements").json()["announcements"]]
    assert "Tonight" in texts


def test_signed_image_proxy_refuses_unsigned_requests(fastapi_client):
    assert fastapi_client.get("/api/v1/images/proxy?u=aHR0cDovL2E=&r=aHR0cDovL2E=&s=bad").status_code in (400, 403)


# --------------------------------------------------------------------------- import gate
def test_import_from_unapproved_site_needs_its_homepage_to_approve_it(fastapi_client):
    admin, _ = _user(UserRole.ADMIN, is_main_admin=True, is_secondary_admin=True)
    host = f"gate-{uuid.uuid4().hex[:8]}.example"
    denied = fastapi_client.post("/api/v1/admin/series", json={"url": f"https://{host}/manga/x"}, headers=admin)
    assert denied.status_code == 422 and denied.json()["error"]["code"] == "WEBSITE_NOT_APPROVED"


def test_import_rejects_a_malformed_mangaupdates_link(fastapi_client):
    admin, _ = _user(UserRole.ADMIN, is_main_admin=True, is_secondary_admin=True)
    resp = fastapi_client.post(
        "/api/v1/admin/series",
        json={"url": "https://x.example/manga/y", "mangaupdates_url": "https://evil.example/series/1/x"},
        headers=admin,
    )
    assert resp.status_code == 422 and resp.json()["error"]["field"] == "mangaupdates_url"


# --------------------------------------------------------------------------- listed sites / domain changes
LISTED_SITES = [
    "baozimh.com", "comic.naver.com", "wujinmh.com", "m.yueman1.cc", "mkzhan.com",
    "m.manhuagui.com", "51manga.com", "m.zymk.cn", "mh03.com", "mh160mh.com",
    "raw.senmanga.com", "mangaz.com", "rawkuma.com", "wfwf505.com",
]
APP_ONLY_SITES = [
    "tonarinoyj.jp", "comic-days.com", "comic-walker.com", "sunday-webry.com",
    "pocket.shonenmagazine.com", "shonenjumpplus.com", "kuaikanmanhua.com",
]


@pytest.mark.parametrize("site", LISTED_SITES)
def test_every_listed_readable_site_has_a_parser(site):
    definition = presets.preset_for_domain(site)
    assert definition and (definition.get("chapter_list") or definition.get("chapter_api"))
    assert "page_images" in definition


@pytest.mark.parametrize("site", APP_ONLY_SITES)
def test_sites_that_cannot_be_fetched_are_declared_unsupported(site):
    assert presets.unsupported_reason(site) and presets.preset_for_domain(site) is None


@pytest.mark.parametrize(
    "moved,original",
    [("wfwf512.com", "wfwf505.com"), ("www.rawkuma.tv", "rawkuma.com"), ("tw.manhuagui.com", "manhuagui.com")],
)
def test_a_renamed_domain_still_finds_its_parser(moved, original):
    assert presets.preset_for_domain(moved) == presets.preset_for_domain(original)


def test_manhuagui_packed_image_list_is_decoded():
    import re

    from backend_fastapi.app.scrapers import packed_scripts as ps

    def enc(n, base):
        head = enc(n // base, base) if n >= base else ""
        rest = n % base
        return head + (chr(rest + 29) if rest > 35 else "0123456789abcdefghijklmnopqrstuvwxyz"[rest])

    plain = (
        'SMH.imgData({"files":["001.jpg.webp","002.jpg.webp"],"path":"/ps1/a/abc/x/",'
        '"sl":{"e":1700000000,"m":"tok"}}).preInit();'
    )
    words = sorted(set(re.findall(r"\b\w+\b", plain)))
    table = {w: enc(i, 62) for i, w in enumerate(words)}
    payload = re.sub(r"\b\w+\b", lambda m: table[m.group(0)], plain)
    packed_words = _lz_compress("|".join(words))
    script = (
        "window[\"\\x65\\x76\\x61\\x6c\"](function(p,a,c,k,e,d){}('%s',62,%d,'%s'"
        "['\\x73\\x70\\x6c\\x69\\x63']('\\x7c'),0,{}))"
        % (payload.replace("\\", "\\\\").replace("'", "\\'"), len(words), packed_words)
    )
    soup = BeautifulSoup(f"<script>{script}</script>", "html.parser")
    assert ps.manhuagui_images(soup) == [
        "https://i.hamreus.com/ps1/a/abc/x/001.jpg.webp?e=1700000000&m=tok",
        "https://i.hamreus.com/ps1/a/abc/x/002.jpg.webp?e=1700000000&m=tok",
    ]


def _lz_compress(text: str) -> str:
    """Minimal LZString ``compressToBase64`` (test helper, mirrors the JS)."""

    keys = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
    dictionary, to_create = {}, set()
    w, enlarge, dict_size, num_bits = "", 2, 3, 2
    out, val, pos = [], 0, 0

    def write(bit):
        nonlocal val, pos
        val = (val << 1) | bit
        pos += 1
        if pos == 6:
            out.append(keys[val])
            val, pos = 0, 0

    def write_bits(value, count):
        for _ in range(count):
            write(value & 1)
            value >>= 1

    def emit_w():
        nonlocal enlarge, num_bits
        if w in to_create:
            code = ord(w[0])
            if code < 256:
                write_bits(0, num_bits)
                write_bits(code, 8)
            else:
                write_bits(1, num_bits)
                write_bits(code, 16)
            enlarge -= 1
            if enlarge == 0:
                enlarge, num_bits = 2**num_bits, num_bits + 1
            to_create.discard(w)
        else:
            write_bits(dictionary[w], num_bits)
        enlarge -= 1
        if enlarge == 0:
            enlarge, num_bits = 2**num_bits, num_bits + 1

    for ch in text:
        if ch not in dictionary:
            dictionary[ch] = dict_size
            dict_size += 1
            to_create.add(ch)
        wc = w + ch
        if wc in dictionary:
            w = wc
            continue
        emit_w()
        dictionary[wc] = dict_size
        dict_size += 1
        w = ch
    if w:
        emit_w()
    write_bits(2, num_bits)
    while True:
        val <<= 1
        pos += 1
        if pos == 6:
            out.append(keys[val])
            break
    return "".join(out) + "=" * ((4 - len(out) % 4) % 4)
