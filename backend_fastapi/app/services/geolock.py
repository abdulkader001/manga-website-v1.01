"""Geolock: refuse the site to visitors from chosen countries.

Settings live in the Secret Vault (``GEOLOCK_ENABLED``,
``GEOLOCK_BLOCKED_COUNTRIES``, ``GEOLOCK_COUNTRY_SOURCE``), so every API and
worker process picks a change up within seconds and the check itself only
reads ``os.environ`` -- no database work per request.

Where a visitor's country comes from:

* ``geoip`` (default): a country database file on this server
  (``<storage>/geoip/country.mmdb``) -- the free DB-IP "IP to Country Lite"
  (downloaded from the Geolock tab, CC BY 4.0) or a MaxMind GeoLite2-Country
  file you upload. Looked up by the client address the app already trusts
  (``utils.client_ip``), never by a header the visitor can set.
* ``cloudflare``: the ``CF-IPCountry`` header Cloudflare adds. Use it only when
  every visitor reaches the site through Cloudflare (otherwise the header can
  be faked).

An address with no known country (private network, missing database) is
let through: a broken lookup must not take the whole site offline.
"""

from __future__ import annotations

import gzip
import ipaddress
import os
import shutil
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional

import requests
import structlog

logger = structlog.get_logger("backend_fastapi.geolock")

ISO_COUNTRIES: FrozenSet[str] = frozenset(
    """
    AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS
    BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE
    EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM
    HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC
    LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA
    NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW
    SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO
    TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS XK YE YT ZA ZM ZW
    """.split()
)

SOURCES = ("geoip", "cloudflare")
DBIP_URL = "https://download.db-ip.com/free/dbip-country-lite-{year}-{month:02d}.mmdb.gz"
MAX_DB_BYTES = 200 * 1024 * 1024
_RECHECK_SECONDS = 60


class GeolockError(ValueError):
    """Bad settings or database (message is safe to show the admin)."""


# --------------------------------------------------------------------------
# Settings (from the vault-backed environment)
# --------------------------------------------------------------------------


@lru_cache(maxsize=32)
def _parse_countries(raw: str) -> FrozenSet[str]:
    return frozenset(c for c in (p.strip().upper() for p in raw.split(",")) if c in ISO_COUNTRIES)


def blocked_countries() -> FrozenSet[str]:
    return _parse_countries(os.getenv("GEOLOCK_BLOCKED_COUNTRIES") or "")


def enabled() -> bool:
    flag = (os.getenv("GEOLOCK_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}
    return flag and bool(blocked_countries())


def source() -> str:
    value = (os.getenv("GEOLOCK_COUNTRY_SOURCE") or "geoip").strip().lower()
    return value if value in SOURCES else "geoip"


def clean_countries(codes) -> list[str]:
    out = sorted({str(c).strip().upper() for c in codes or [] if str(c).strip()})
    unknown = [c for c in out if c not in ISO_COUNTRIES]
    if unknown:
        raise GeolockError(f"Unknown country codes: {', '.join(unknown)}")
    return out


# --------------------------------------------------------------------------
# Country database
# --------------------------------------------------------------------------


def db_path() -> Path:
    from .backup_service import storage_root

    configured = os.getenv("GEOIP_DATABASE_PATH")
    return Path(configured) if configured else storage_root() / "geoip" / "country.mmdb"


class _ReaderCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._reader = None
        self._mtime: Optional[float] = None
        self._checked = 0.0

    def get(self):
        now = time.monotonic()
        if now - self._checked < _RECHECK_SECONDS and self._checked:
            return self._reader
        with self._lock:
            self._checked = now
            path = db_path()
            try:
                mtime = path.stat().st_mtime
            except OSError:
                self._close()
                return None
            if mtime != self._mtime:
                self._close()
                try:
                    import maxminddb

                    self._reader = maxminddb.open_database(str(path))
                    self._mtime = mtime
                    _lookup.cache_clear()
                except Exception:
                    logger.warning("geoip_database_unreadable", path=str(path))
                    self._reader = None
            return self._reader

    def _close(self):
        if self._reader is not None:
            try:
                self._reader.close()
            except Exception:
                pass
        self._reader = None
        self._mtime = None

    def reset(self):
        with self._lock:
            self._close()
            self._checked = 0.0
        _lookup.cache_clear()


_readers = _ReaderCache()


@lru_cache(maxsize=20000)
def _lookup(ip: str) -> Optional[str]:
    reader = _readers.get()
    if reader is None:
        return None
    try:
        record = reader.get(ip)
    except (ValueError, TypeError):
        return None
    if not isinstance(record, dict):
        return None
    country = record.get("country") or record.get("registered_country") or {}
    code = country.get("iso_code") if isinstance(country, dict) else None
    return code.upper() if isinstance(code, str) else None


def country_for_ip(ip: str) -> Optional[str]:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
        return None
    _readers.get()  # refresh (and clear the cache) when the file changed
    return _lookup(str(address))


def country_for_request(request, via: Optional[str] = None) -> Optional[str]:
    if (via or source()) == "cloudflare":
        code = (request.headers.get("cf-ipcountry") or "").strip().upper()
        return code if code in ISO_COUNTRIES else None
    from ..utils.client_ip import resolve_client_ip

    return country_for_ip(resolve_client_ip(request))


def is_blocked(request) -> bool:
    if not enabled():
        return False
    country = country_for_request(request)
    return country is not None and country in blocked_countries()


def database_status() -> Dict[str, Any]:
    path = db_path()
    if not path.is_file():
        return {"installed": False}
    info: Dict[str, Any] = {
        "installed": True,
        "size": path.stat().st_size,
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="minutes"),
    }
    reader = _readers.get()
    if reader is not None:
        meta = reader.metadata()
        info["type"] = meta.database_type
        info["built_at"] = datetime.fromtimestamp(meta.build_epoch, timezone.utc).date().isoformat()
    else:
        info["installed"] = False
        info["error"] = "The file is not a readable country database."
    return info


def install_database(candidate: Path) -> Dict[str, Any]:
    """Check ``candidate`` is a country .mmdb, then make it the live database."""

    try:
        import maxminddb

        with maxminddb.open_database(str(candidate)) as reader:
            kind = reader.metadata().database_type or ""
    except Exception as exc:
        candidate.unlink(missing_ok=True)
        raise GeolockError("That file is not a GeoIP (.mmdb) database.") from exc
    if "country" not in kind.lower() and "city" not in kind.lower():
        candidate.unlink(missing_ok=True)
        raise GeolockError(f"That database is '{kind}', not a country database.")
    target = db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(candidate, target)
    _readers.reset()
    logger.info("geoip_database_installed", type=kind)
    return database_status()


def download_dbip(now: Optional[datetime] = None, session: Optional[requests.Session] = None) -> Dict[str, Any]:
    """Fetch this month's free DB-IP country database (falls back to last month)."""

    now = now or datetime.now(timezone.utc)
    session = session or requests.Session()
    target_dir = db_path().parent
    target_dir.mkdir(parents=True, exist_ok=True)
    last_error = "no response"
    for month_start in (now, now.replace(day=1) - timedelta(days=1)):
        url = DBIP_URL.format(year=month_start.year, month=month_start.month)
        try:
            response = session.get(url, stream=True, timeout=(15, 120))
        except requests.RequestException as exc:
            last_error = exc.__class__.__name__
            continue
        if response.status_code != 200:
            last_error = f"HTTP {response.status_code}"
            response.close()
            continue
        fd, raw_name = tempfile.mkstemp(dir=target_dir, suffix=".gz.part")
        raw = Path(raw_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                written = 0
                for chunk in response.iter_content(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_DB_BYTES:
                        raise GeolockError("The download was larger than expected and was stopped.")
                    fh.write(chunk)
            fd2, db_name = tempfile.mkstemp(dir=target_dir, suffix=".mmdb.part")
            with os.fdopen(fd2, "wb") as out, gzip.open(raw, "rb") as gz:
                shutil.copyfileobj(gz, out, 1024 * 1024)
            return install_database(Path(db_name))
        except (OSError, EOFError) as exc:
            raise GeolockError("The downloaded database was damaged. Try again later.") from exc
        finally:
            raw.unlink(missing_ok=True)
            response.close()
    raise GeolockError(f"Could not download the DB-IP database ({last_error}). Upload a .mmdb file instead.")


__all__ = [
    "GeolockError",
    "ISO_COUNTRIES",
    "SOURCES",
    "blocked_countries",
    "clean_countries",
    "country_for_ip",
    "country_for_request",
    "database_status",
    "db_path",
    "download_dbip",
    "enabled",
    "install_database",
    "is_blocked",
    "source",
]
