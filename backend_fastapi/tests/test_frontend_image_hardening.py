"""Guard the properties of the shipped `web` image that no code module owns.

Two of the three production blockers found by the Part 14 audit lived here and
were invisible to every existing test, because they are properties of the
Docker build and the nginx config rather than of any Python or JS module:

* **F-71** — the build emitted ``.map`` files with ``sourcesContent: true``,
  so the complete original text of the frontend was downloadable over HTTP.
* **F-74** — ``frontend/nginx.conf`` held the security headers, gzip and cache
  rules, but nothing referenced it; ``web.Dockerfile`` shipped the *root*
  ``nginx.conf``, which had none of them.

Both are one-line mistakes that survive any amount of unit testing, so they
are asserted directly against the build inputs here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DOCKERFILE = REPO_ROOT / "web.Dockerfile"
SITE_CONF = REPO_ROOT / "nginx.conf"


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return WEB_DOCKERFILE.read_text()


@pytest.fixture(scope="module")
def site_conf() -> str:
    return SITE_CONF.read_text()


def test_build_disables_source_maps(dockerfile: str) -> None:
    assert re.search(r"^ENV GENERATE_SOURCEMAP=false", dockerfile, re.MULTILINE), (
        "F-71: the frontend build must not emit .map files -- they contain the "
        "complete original source of every module."
    )


def test_build_fails_if_a_source_map_survives(dockerfile: str) -> None:
    assert "-name '*.map' -delete" in dockerfile
    assert "exit 1" in dockerfile, (
        "Deleting the maps is not enough on its own -- the build must fail "
        "loudly if any survive, or a future CRA change silently reships them."
    )


def test_image_ships_the_hardened_site_config(dockerfile: str) -> None:
    assert "COPY nginx.conf /etc/nginx/conf.d/default.conf" in dockerfile
    # The two configs that used to hold these rules while nothing referenced
    # them are gone; if either reappears, the ambiguity F-74 came from is back.
    assert not (REPO_ROOT / "frontend" / "nginx.conf").exists()
    assert not (REPO_ROOT / "nginx" / "conf.d" / "default.conf").exists()


def test_vite_build_emits_no_inline_script(dockerfile: str) -> None:
    """Required by the CSP: `script-src 'self'` forbids inline scripts.

    Vite (unlike CRA's inline webpack runtime) emits only `<script src>` tags;
    the image must build with it and CI asserts the result stays that way.
    """

    assert re.search(r"^RUN npm run build", dockerfile, re.MULTILINE)
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "index.html carries no inline script" in ci


@pytest.mark.parametrize(
    "header",
    [
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "Content-Security-Policy",
    ],
)
def test_site_config_sets_security_header(site_conf: str, header: str) -> None:
    assert re.search(rf"add_header\s+{re.escape(header)}\b", site_conf), (
        f"F-74: {header} is missing from the config the image actually ships."
    )


def test_csp_forbids_inline_and_eval_scripts(site_conf: str) -> None:
    match = re.search(r"add_header Content-Security-Policy\s+\"([^\"]+)\"", site_conf)
    assert match, "no Content-Security-Policy header found"
    policy = match.group(1)

    script_src = next(
        (part.strip() for part in policy.split(";") if part.strip().startswith("script-src")),
        None,
    )
    assert script_src, "CSP has no script-src directive"
    assert "'unsafe-inline'" not in script_src
    # 'wasm-unsafe-eval' is required for the OCR WebAssembly and is NOT
    # 'unsafe-eval' -- it permits WebAssembly compilation only.
    assert "'unsafe-eval'" not in script_src.replace("'wasm-unsafe-eval'", "")
    assert "frame-ancestors 'none'" in policy
    assert "base-uri 'none'" in policy
    assert "object-src" in policy or "default-src 'none'" in policy


def test_site_config_enables_compression(site_conf: str) -> None:
    assert re.search(r"^\s*gzip on;", site_conf, re.MULTILINE), (
        "F-74: without gzip the main bundle ships at ~3x its compressed size."
    )
    assert "application/javascript" in site_conf
    assert "text/css" in site_conf


def test_wasm_is_compressed(site_conf: str) -> None:
    """The OCR runtime is 25.6 MB raw and 6.0 MB gzipped.

    `application/wasm` was missing from gzip_types, so every reader who opened
    the OCR overlay downloaded the full 25.6 MB. It is the single largest
    asset the site can serve -- 60x the main bundle.
    """

    gzip_types = re.search(r"gzip_types(.*?);", site_conf, re.DOTALL)
    assert gzip_types is not None, "gzip_types block missing"
    assert "application/wasm" in gzip_types.group(1), (
        "application/wasm must be gzipped: the PP-OCRv5 runtime is 25.6 MB "
        "uncompressed versus 6.0 MB gzipped"
    )


def test_hashed_assets_are_cached_and_index_is_not(site_conf: str) -> None:
    assert "immutable" in site_conf, "fingerprinted assets must be cached forever"
    index_block = re.search(
        r"location = /index\.html \{(.*?)\n  \}", site_conf, re.DOTALL
    )
    assert index_block, "no explicit /index.html location"
    assert "no-store" in index_block.group(1), (
        "index.html points at the hashed asset names, so caching it pins "
        "visitors to a stale deploy."
    )


def test_source_maps_are_unreachable_over_http(site_conf: str) -> None:
    assert re.search(r"location ~\* \\\.map\$", site_conf), (
        "Belt and braces for F-71: a .map that slips into an image must still "
        "404 rather than serve."
    )


def test_healthcheck_reflects_backend_reachability(site_conf: str) -> None:
    """F-50: a static `return 200 'ok'` reports healthy through an outage."""

    healthz = re.search(r"location = /healthz \{(.*?)\n  \}", site_conf, re.DOTALL)
    assert healthz, "no /healthz location"
    assert "proxy_pass" in healthz.group(1)


def test_admin_allowlist_targets_the_canonical_mount(site_conf: str) -> None:
    """F-69: the commented allowlist must match the prefix the app serves."""

    assert "/api/admin/ {" not in site_conf, (
        "The application mounts admin routes under /api/v1/admin/; an "
        "allowlist keyed to /api/admin/ would 404 every admin request the "
        "moment an operator enabled it."
    )
    assert "location /api/v1/admin/" in site_conf


def test_site_config_braces_balance(site_conf: str) -> None:
    """Cheap structural check -- there is no nginx binary in CI to run -t."""

    stripped = "\n".join(
        line.split("#", 1)[0] for line in site_conf.splitlines()
    )
    assert stripped.count("{") == stripped.count("}") != 0
