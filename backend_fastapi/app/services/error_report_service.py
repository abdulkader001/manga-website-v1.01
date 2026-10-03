"""Record errors for Admin -> Error Report and explain them in plain language.

``record`` never raises: a broken error log must not turn one error into two.
It opens its own database session, so it can be called from the exception
handler, a worker signal or the browser-report route alike.

``diagnose`` matches the error against ``RULES`` (first match wins) and returns
a category, the likely cause and what to do. The rules are written for the site
owner, not for a developer: they name the setting, page or command to use.
"""

from __future__ import annotations

import hashlib
import re
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog

from ..models import ErrorReport
from ..models.error_report import SOURCE_BROWSER, SOURCE_SERVER, SOURCE_WORKER, SOURCES

logger = structlog.get_logger(__name__)

MAX_MESSAGE = 2000
MAX_STACK = 8000
MAX_KIND = 128
MAX_LOCATION = 255
# Oldest rows past this are dropped, so a storm of new errors can't fill the disk.
MAX_ROWS = 2000

# ----------------------------------------------------------------- scrubbing

_SCRUB = (
    # e-mail addresses
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
    # credentials inside URLs: scheme://user:password@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1[credentials]@"),
    # bearer / API keys / tokens / passwords given as key=value or key: value
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+"), r"\1 [token]"),
    (
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|passwd|pwd|signature|sig)"
            r"(\s*[=:]\s*|\"\s*:\s*\")[^\s&\"',;]+"
        ),
        r"\1\2[hidden]",
    ),
    # one-time codes in URLs (magic links, OAuth callbacks)
    (re.compile(r"(?i)([?&](?:code|state|key)=)[^\s&#\"']+"), r"\1[hidden]"),
    # JSON web tokens
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[token]"),
    # IPv4 and IPv6 addresses (visitors' IPs are for the owner only, and never logged)
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[ip]"),
    (re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){3,7}[0-9a-fA-F]{1,4}\b"), "[ip]"),
    # long opaque strings (keys, session ids)
    (re.compile(r"\b[A-Za-z0-9_-]{40,}\b"), "[hidden]"),
)


def scrub(value: str | None, limit: int) -> str | None:
    """Mask e-mails, IPs, tokens and passwords, and cut to ``limit`` characters."""

    if not value:
        return None
    text = str(value)
    for pattern, replacement in _SCRUB:
        text = pattern.sub(replacement, text)
    text = text.strip()
    if len(text) > limit:
        # Keep the end of a stack (where the error is), the start of a message.
        text = ("…" + text[-(limit - 1):]) if "\n" in text else (text[: limit - 1] + "…")
    return text or None


def _strip_query(location: str | None) -> str | None:
    if not location:
        return None
    return location.split("?", 1)[0].split("#", 1)[0][:MAX_LOCATION] or None


_VOLATILE = re.compile(r"0x[0-9a-fA-F]+|\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27}\b|\d+")


def fingerprint(source: str, kind: str, message: str | None, location: str | None) -> str:
    """The same error at the same place is one row, whatever ids or numbers it names."""

    stable = _VOLATILE.sub("#", (message or "")[:300])
    loc = _VOLATILE.sub("#", location or "")
    raw = "\x1f".join((source, kind, stable, loc))
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()


# ----------------------------------------------------------------- diagnosis


@dataclass(frozen=True)
class Rule:
    category: str
    pattern: re.Pattern
    cause: str
    fix: str
    sources: tuple[str, ...] = SOURCES


def _rule(category, pattern, cause, fix, sources=SOURCES) -> Rule:
    return Rule(category, re.compile(pattern, re.IGNORECASE), cause, fix, tuple(sources))


_SERVER = (SOURCE_SERVER, SOURCE_WORKER)

# Matched against "kind: message\nstack". First match wins, so the specific
# rules come before the general ones.
RULES: tuple[Rule, ...] = (
    # ---- database
    _rule(
        "database",
        r"no such table|no such column|UndefinedTable|UndefinedColumn|relation \"[^\"]+\" does not exist|column \"[^\"]+\" (of relation \"[^\"]+\" )?does not exist",
        "The database is missing a table or column the code expects. The site was updated but the database was not.",
        "Run the database update on the server: `alembic upgrade head` (or `deployment/migrate.sh`), then restart the API and workers. GUIDE.md -> Updating the site.",
        _SERVER,
    ),
    _rule(
        "database",
        r"could not connect to server|connection refused.*(5432|postgres)|password authentication failed|OperationalError.*(connect|terminat)|database .* does not exist|too many clients|remaining connection slots",
        "The API can't reach the database, or the database refused the login or ran out of connections.",
        "Check the database is running (`docker compose ps` / `systemctl status postgresql`) and that `DATABASE_URL` in `.env` is right. If it says too many clients, restart the API or raise the database's max_connections.",
        _SERVER,
    ),
    _rule(
        "database",
        r"QueuePool limit|TimeoutError.*pool|connection timed out.*pool",
        "Every database connection was busy, so the request gave up waiting. The site is overloaded or a slow query is holding connections.",
        "Look at Admin -> System Health for slow queries and load. Restart the API to free stuck connections; if it keeps happening, raise SQLALCHEMY_POOL_SIZE or add a worker.",
        _SERVER,
    ),
    _rule(
        "database",
        r"statement timeout|canceling statement due to",
        "A database query ran longer than the allowed time and was stopped.",
        "Usually a missing index or a very large table. Note the page in 'Where' and check Admin -> System Health; running `alembic upgrade head` adds any indexes the update shipped.",
        _SERVER,
    ),
    _rule(
        "database",
        r"IntegrityError|UniqueViolation|duplicate key|UNIQUE constraint failed|ForeignKeyViolation|NotNullViolation|NOT NULL constraint",
        "The code tried to save something the database refused: a duplicate, or a row pointing at something that no longer exists.",
        "Often two clicks at once or something deleted meanwhile; trying again usually works. If it repeats at the same place, it is a code bug: send this entry (with Technical details) to the developer.",
        _SERVER,
    ),
    # ---- cache / queue
    _rule(
        "redis",
        r"redis|Error \d+ connecting to|ConnectionError.*6379|kombu\.exceptions\.OperationalError",
        "Redis (the cache and task queue) can't be reached, so background jobs and some limits don't work.",
        "Check Redis is running (`docker compose ps redis` / `systemctl status redis`) and that `REDIS_URL` in `.env` is right, then restart the workers.",
        _SERVER,
    ),
    # ---- disk / memory / files
    _rule(
        "server",
        r"No space left on device|Disk quota exceeded|ENOSPC",
        "The server's disk is full.",
        "Free space: delete old backups in Admin -> Storage & Backups, clear the image cache, or grow the disk. Check with `df -h` on the server.",
        _SERVER,
    ),
    _rule(
        "server",
        r"MemoryError|Cannot allocate memory|out of memory|OOM|WorkerLostError|SIGKILL",
        "The server ran out of memory and the process was stopped.",
        "Lower the number of workers/threads or the OCR batch size, or give the server more RAM. Admin -> System Health shows memory use.",
        _SERVER,
    ),
    _rule(
        "server",
        r"PermissionError|Permission denied|EACCES|Read-only file system",
        "The server process is not allowed to write a file or folder it needs.",
        "Give the app's user ownership of the storage folders (for example `chown -R` the media/backups folders), then restart.",
        _SERVER,
    ),
    _rule(
        "server",
        r"FileNotFoundError|No such file or directory",
        "A file the code expected is missing (an image, font, model or backup).",
        "Check the path shown in Technical details exists on the server. Re-scrape the chapter if it is a page image, or re-upload the missing asset.",
        _SERVER,
    ),
    _rule(
        "server",
        r"ModuleNotFoundError|ImportError|No module named",
        "A Python package the code needs is not installed on the server.",
        "Install the packages again: `pip install -r backend_fastapi/requirements.txt` (or rebuild the Docker image), then restart.",
        _SERVER,
    ),
    # ---- outside services
    _rule(
        "provider",
        r"(status|HTTP|code)\D{0,6}40[13]\b.*(openai|anthropic|google|deepl|azure|gemini|provider|api key)|invalid[_ ]api[_ ]key|incorrect api key|PROVIDER_FAILED.*(40[13]|unauthori)|Unauthorized.*(api|key)",
        "An OCR / translation / AI provider refused the API key (wrong, expired or out of credit).",
        "Open Admin -> API Management, test the provider and replace its key, or switch to another provider.",
        _SERVER,
    ),
    _rule(
        "provider",
        r"(status|HTTP|code)\D{0,6}429\b|rate.?limit|quota|Too Many Requests|insufficient_quota",
        "An outside service (a source site or an API provider) is rate-limiting us: too many requests in a short time.",
        "Wait and retry. For a provider, check its plan or quota in Admin -> API Management; for a source site, slow the scraper schedule in Series Management.",
        _SERVER,
    ),
    _rule(
        "scraper",
        r"SCRAPER_EXTRACTION_FAILED|selector|parser|no chapters found|no images found|extraction",
        "The scraper reached the source site but couldn't find the chapters or images, usually because the site changed its layout.",
        "Open Series Management -> Websites, re-test the source and regenerate its parser with the Scraper AI (Custom Parser) or roll back to a working version.",
        _SERVER,
    ),
    _rule(
        "scraper",
        r"Cloudflare|cf-chl|captcha|403 Forbidden|(status|HTTP|code)\D{0,6}403\b|Access denied",
        "A source website blocked the scraper (Cloudflare, captcha or bot protection).",
        "Try again later or from another server address, add a proxy if you use one, or remove the source in Series Management -> Websites.",
        _SERVER,
    ),
    _rule(
        "provider",
        r"PROVIDER_FAILED",
        "An OCR / translation / AI provider returned an error or no usable result.",
        "Open Admin -> API Management and press Test on the provider. Replace the key, check its credit, or move another provider to the top of the list.",
        _SERVER,
    ),
    _rule(
        "scraper",
        r"SCRAPER_UNAVAILABLE",
        "The scraper service isn't running or can't take the job right now.",
        "Check the workers are running (Admin -> System Health, or `systemctl status manga-worker`) and that Scraping is switched on in Site Functions.",
        _SERVER,
    ),
    _rule(
        "network",
        r"SSLError|CERTIFICATE_VERIFY_FAILED|certificate verify failed|SSL: ",
        "A secure (HTTPS) connection to an outside site failed its certificate check.",
        "The other site's certificate is broken or the server's clock is wrong. Check the server's date/time and update its CA certificates (`apt install ca-certificates`).",
        _SERVER,
    ),
    _rule(
        "network",
        r"ReadTimeout|ConnectTimeout|TimeoutError|timed out|GATEWAY_TIMEOUT|(status|HTTP|code)\D{0,6}504\b",
        "An outside site or service took too long to answer.",
        "Usually temporary: retry. If one source or provider is always slow, check it is up, or replace it in Series Management / API Management.",
        _SERVER,
    ),
    _rule(
        "network",
        r"ConnectionError|ConnectError|Name or service not known|getaddrinfo|Temporary failure in name resolution|Connection reset|RemoteDisconnected|BAD_GATEWAY|(status|HTTP|code)\D{0,6}502\b",
        "The server couldn't connect to an outside website or service (it is down, the address is wrong, or DNS failed).",
        "Check the address in the source or provider settings and that the server has internet access. Retry later if the other site is down.",
        _SERVER,
    ),
    _rule(
        "email",
        r"SMTP|smtplib|Authentication unsuccessful|535 ",
        "Sending an e-mail (magic link or alert) failed: the mail server refused the login or can't be reached.",
        "Check the SMTP settings in Admin -> Secret Vault (host, port, user, password) and send a test e-mail.",
        _SERVER,
    ),
    _rule(
        "config",
        r"(?-i:KeyError: '[A-Z][A-Z0-9_]{2,}')|environment variable|not configured|missing setting|is not set",
        "A setting the code needs is missing.",
        "Add the missing value in Admin -> Secret Vault (or `.env` for database, Redis, site address and keys), then restart.",
        _SERVER,
    ),
    _rule(
        "data",
        r"JSONDecodeError|Expecting value|Unterminated string|ValidationError",
        "Some data couldn't be read: an outside service answered with something that isn't the expected format, or a stored value is damaged.",
        "If it comes from a provider or source site, test it in API Management / Series Management. If it repeats at one page, send this entry to the developer.",
        _SERVER,
    ),
    # ---- browser
    _rule(
        "update",
        r"ChunkLoadError|Loading chunk \S+ failed|Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module",
        "The reader's browser still had the old version of the site open after an update, so a page part it asked for no longer exists.",
        "Nothing is broken: a refresh fixes it for the reader. If it keeps appearing long after an update, make sure the web server doesn't cache index.html (GUIDE.md -> Updating the site).",
        (SOURCE_BROWSER,),
    ),
    _rule(
        "network",
        r"Failed to fetch|NetworkError|Load failed|Unable to reach the FastAPI backend|ERR_NETWORK|ERR_INTERNET_DISCONNECTED",
        "The browser couldn't reach the API: the reader's internet dropped, the API is down, or the API doesn't allow the site's address.",
        "If many readers report it, check the API is running (Admin -> System Health) and that ALLOWED_ORIGINS in `.env` includes the site address. One-off entries are usually the reader's connection.",
        (SOURCE_BROWSER,),
    ),
    _rule(
        "harmless",
        r"ResizeObserver loop|Non-Error promise rejection captured|AbortError|The user aborted a request|cancel(l)?ed",
        "A harmless browser notice (a cancelled request or a layout warning), not a real fault.",
        "No action needed. Mark it fixed to hide it.",
        (SOURCE_BROWSER,),
    ),
    _rule(
        "extension",
        r"(^|: )Script error\.?$|chrome-extension://|moz-extension://|safari-extension://|adsbygoogle|googletag|doubleclick",
        "The error came from a browser extension or an ad script, not from the site's own code, so the browser hides the details.",
        "Usually nothing to do. If it comes from an ad network, check the ad code in Admin -> Ads & Placements.",
        (SOURCE_BROWSER,),
    ),
    _rule(
        "storage",
        r"QuotaExceededError|localStorage|exceeded the quota",
        "The reader's browser storage is full, so bookmarks or reading history couldn't be saved.",
        "The reader can clear old site data in their browser. If it is common, tell the developer to keep less in browser storage.",
        (SOURCE_BROWSER,),
    ),
    _rule(
        "code",
        r"Cannot read propert|undefined is not an object|is not a function|is not iterable|null is not an object|Cannot destructure|is not defined|Minified React error",
        "A bug in the site's page code: it expected some data that wasn't there (often the API answered with an error or a different shape).",
        "Send this entry with Technical details to the developer. Check the page in 'Where' and whether a server error was reported at the same time.",
        (SOURCE_BROWSER,),
    ),
    # ---- general code bugs (server)
    _rule(
        "code",
        r"AttributeError|TypeError|KeyError|IndexError|NameError|ValueError|ZeroDivisionError|UnboundLocalError|AssertionError|NotImplementedError|RecursionError",
        "A bug in the server code: it hit a case it doesn't handle (missing data, an unexpected value).",
        "Send this entry with Technical details to the developer; the last lines of the stack show the file and line. Until then, note what was being done when it happened.",
        _SERVER,
    ),
)

_UNKNOWN = (
    "unknown",
    "No known pattern matched this error.",
    "Open Technical details: the first line names the error and the last stack lines show where it happened. Send it to the developer if it keeps repeating.",
)


def diagnose(source: str, kind: str, message: str | None, stack: str | None) -> tuple[str, str, str]:
    """``(category, cause, fix)`` for an error, in plain language."""

    head = f"{kind}: {message or ''}"
    haystack = f"{head}\n{stack or ''}"
    for rule in RULES:
        if source not in rule.sources:
            continue
        # The error's own name and message decide first; the stack only as a fallback.
        if rule.pattern.search(head):
            return rule.category, rule.cause, rule.fix
    for rule in RULES:
        if source in rule.sources and rule.pattern.search(haystack):
            return rule.category, rule.cause, rule.fix
    return _UNKNOWN


# ----------------------------------------------------------------- recording


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record(
    *,
    source: str,
    kind: str,
    message: str | None = None,
    location: str | None = None,
    stack: str | None = None,
) -> int | None:
    """Add one occurrence. Returns the row id, or ``None`` when it couldn't be saved."""

    try:
        from ..core.db import SessionLocal

        if source not in SOURCES:
            return None
        kind = (scrub(kind, MAX_KIND) or "Error")[:MAX_KIND]
        message = scrub(message, MAX_MESSAGE)
        location = scrub(_strip_query(location), MAX_LOCATION)
        stack = scrub(stack, MAX_STACK)
        key = fingerprint(source, kind, message, location)
        now = _now()
        with SessionLocal() as session:
            row = session.query(ErrorReport).filter(ErrorReport.fingerprint == key).one_or_none()
            if row is None:
                category, cause, fix = diagnose(source, kind, message, stack)
                row = ErrorReport(
                    fingerprint=key, source=source, kind=kind, message=message,
                    location=location, stack=stack, category=category, cause=cause,
                    fix=fix, count=1, first_seen=now, last_seen=now, resolved=False,
                )
                session.add(row)
                session.flush()
                _trim(session)
            else:
                row.count = (row.count or 0) + 1
                row.last_seen = now
                if stack:
                    row.stack = stack
                if row.resolved:
                    # It came back after being marked fixed: show it again.
                    row.resolved = False
                    row.resolved_at = None
                    row.resolved_by = None
            session.commit()
            return row.id
    except Exception:  # pragma: no cover - depends on the database being broken
        logger.warning("error_report_record_failed", exc_info=True)
        return None


def _trim(session) -> None:
    total = session.query(ErrorReport.id).count()
    if total <= MAX_ROWS:
        return
    old = (
        session.query(ErrorReport.id)
        .order_by(ErrorReport.resolved.desc(), ErrorReport.last_seen.asc())
        .limit(total - MAX_ROWS)
        .all()
    )
    session.query(ErrorReport).filter(ErrorReport.id.in_([r.id for r in old])).delete(synchronize_session=False)


def record_exception(exc: BaseException, *, source: str, location: str | None = None, kind: str | None = None) -> int | None:
    stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return record(
        source=source,
        kind=kind or type(exc).__name__,
        message=str(exc) or type(exc).__name__,
        location=location,
        stack=stack,
    )


# ----------------------------------------------------------------- reading


def serialize(row: ErrorReport) -> dict:
    return {
        "id": row.id,
        "source": row.source,
        "kind": row.kind,
        "message": row.message,
        "location": row.location,
        "stack": row.stack,
        "category": row.category,
        "cause": row.cause,
        "fix": row.fix,
        "count": row.count,
        "first_seen": row.first_seen.isoformat() + "Z" if row.first_seen else None,
        "last_seen": row.last_seen.isoformat() + "Z" if row.last_seen else None,
        "resolved": bool(row.resolved),
        "resolved_at": row.resolved_at.isoformat() + "Z" if row.resolved_at else None,
    }
