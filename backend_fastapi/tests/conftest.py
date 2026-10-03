"""Pytest fixtures for the FastAPI backend."""

from __future__ import annotations

import importlib.util
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

_HTTPX_STUB = Path(__file__).resolve().parent / "_support" / "httpx_stub"

if "httpx" not in os.sys.modules:
    spec = importlib.util.spec_from_file_location(
        "httpx",
        _HTTPX_STUB / "__init__.py",
        submodule_search_locations=[str(_HTTPX_STUB)],
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    module.__path__ = [str(_HTTPX_STUB)]  # type: ignore[attr-defined]
    # The stub's __init__ does `from . import _client, _types`. A relative
    # import resolves its parent through sys.modules, so the module has to be
    # registered *before* it is executed -- otherwise Python falls back to
    # importing whatever `httpx` is on sys.path (the real package, whose
    # `_client` is not this one) or fails outright under pytest's import hook.
    os.sys.modules["httpx"] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del os.sys.modules["httpx"]
        raise

    # Mock AsyncClient and exceptions for the tests since the stub doesn't have them
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aclose(self):
            pass

    class HTTPError(Exception):
        pass

    class RequestError(HTTPError):
        def __init__(self, message, request=None):
            super().__init__(message)
            self.request = request

    class HTTPStatusError(HTTPError):
        def __init__(self, message, request=None, response=None):
            super().__init__(message)
            self.request = request
            self.response = response

    module.AsyncClient = MockAsyncClient
    module.HTTPError = HTTPError
    module.RequestError = RequestError
    module.HTTPStatusError = HTTPStatusError

# ---------------------------------------------------------------------------
# Environment bootstrap
# ---------------------------------------------------------------------------
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("MAGIC_LINK_SECRET", "test-magic-secret")
os.environ.setdefault("INTEGRATIONS_SECRET", "test-integrations-secret")
os.environ.setdefault(
    "EMAIL_ENCRYPTION_KEY", "XbI7VwMT8sh/IVCrqyVYgK8/XWiwxupCSvJzpuG1Hs8="
)
os.environ.setdefault("OCR_MODE", "remote")
os.environ.setdefault("REMOTE_OCR_URL", "https://example.com/ocr")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_fastapi.db")
os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "True")
os.environ.setdefault("CELERY_BROKER_URL", "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")
os.environ.setdefault("FORCE_HTTPS_REDIRECTS", "false")
os.environ.setdefault("ALLOW_PLAINTEXT_SECRETS", "1")
os.environ.setdefault("TESTING", "1")
# The whole suite shares one client IP; the generic 300 req/60s IP limiter
# starts flaking as the suite grows. Endpoint-specific limits stay active.
os.environ.setdefault("GENERIC_RATE_LIMIT_REQUESTS", "100000")

from fastapi.testclient import TestClient  # noqa: E402

from backend_fastapi.app.core.settings import settings  # noqa: E402

settings.force_https_redirects = False

_DB_PATH = Path("test_fastapi.db")
if _DB_PATH.exists():
    _DB_PATH.unlink()


def _install_security_stubs() -> None:
    """Replace password hashing with deterministic helpers for tests."""

    from backend_fastapi.app.core import security as fastapi_security

    def fake_hash(password: str) -> str:
        return f"hashed::{password}"

    def fake_verify(plain: str, hashed: str) -> bool:
        return hashed == fake_hash(plain)

    fastapi_security.get_password_hash = fake_hash  # type: ignore[assignment]
    fastapi_security.verify_password = fake_verify  # type: ignore[assignment]


_install_security_stubs()


@contextmanager
def _session_scope() -> Iterator:
    from backend_fastapi.app.core.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _set_members_only_default(value: bool) -> None:
    """Change what a missing/new ``system_settings.login_required`` means."""

    from backend_fastapi.app.dependencies import site_access
    from backend_fastapi.app.models import SystemSettings

    site_access.LOGIN_REQUIRED_DEFAULT = value
    SystemSettings.__table__.c.login_required.default.arg = value


@pytest.fixture(autouse=True)
def _site_open_to_guests():
    """The site is members-only by default (sign-in required). Most tests read
    the catalogue as a guest, so they run with the default switched off; a
    test of the real default asks for ``members_only_default``."""

    _set_members_only_default(False)
    yield
    _set_members_only_default(True)


@pytest.fixture
def members_only_default():
    _set_members_only_default(True)
    yield


@pytest.fixture(scope="session")
def fastapi_app():
    from backend_fastapi.app.main import create_app
    from backend_fastapi.app.core.db import Base, engine

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return create_app()


@pytest.fixture(scope="session")
def fastapi_client(fastapi_app):
    with TestClient(fastapi_app) as client:
        yield client


@pytest.fixture
def db_session():
    with _session_scope() as session:
        yield session


@pytest.fixture
def auth_headers():
    """Bearer headers for a plain registered user.

    Processing endpoints (OCR/translation/AI) require login (SRS 1D.3), so
    tests that exercise them must authenticate.
    """
    import uuid

    from backend_fastapi.app.core.security import create_access_token
    from backend_fastapi.app.models import User, UserRole

    with _session_scope() as session:
        user = User(
            email=f"user-{uuid.uuid4().hex}@example.com",
            is_active=True,
            name="Test User",
            role=UserRole.USER,
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        user_id = user.id
    return {"Authorization": f"Bearer {create_access_token(str(user_id))}"}


@pytest.fixture
def sample_data(db_session):
    from backend_fastapi.app.models import Chapter, Manga, User

    from _support.db_reset import clear_users_and_content

    clear_users_and_content(db_session)

    user = User(
        email="user@example.com",
        is_active=True,
        name="Test User",
        provider="magic_link",
    )
    db_session.add(user)

    manga = Manga(
        title="Test Manga",
        slug="test-manga",
        cover_image="cover.jpg",
        description="A test manga used for API assertions.",
        source_url="https://example.com/manga/test",
        language="en",
        genres=["action", "comedy"],
        popularity=123,
    )
    db_session.add(manga)
    db_session.flush()

    chapter = Chapter(
        manga_id=manga.id,
        chapter_number=1,
        chapter_title="Pilot",
        chapter_url="https://example.com/manga/test/1",
    )
    db_session.add(chapter)
    db_session.commit()

    return {"user": user, "manga": manga, "chapter": chapter}
