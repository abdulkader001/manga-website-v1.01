"""scripts/make_env.py: a fresh .env with matching, random secrets."""

from __future__ import annotations

import re

from cryptography.fernet import Fernet

from backend_fastapi.scripts import make_env


def _value(text: str, key: str) -> str:
    return re.search(rf"(?m)^{key}=(.*)$", text).group(1)


def test_fresh_env_has_new_secrets_and_matching_passwords():
    template = (make_env.ROOT / ".env.example").read_text(encoding="utf-8")
    text = make_env.build(template, local=False)
    assert "example-postgres-password" not in text and "example-redis-password" not in text
    for key in ("SECRET_KEY", "JWT_SECRET_KEY", "MAGIC_LINK_SECRET", "INTEGRATIONS_SECRET"):
        assert _value(text, key) != _value(template, key)
        assert len(_value(text, key)) == 64
    Fernet(_value(text, "EMAIL_ENCRYPTION_KEY"))  # a valid key
    pg = _value(text, "POSTGRES_PASSWORD")
    assert f"manga:{pg}@db" in _value(text, "DATABASE_URL")
    redis = _value(text, "REDIS_PASSWORD")
    for key in ("REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND"):
        assert f"default:{redis}@redis" in _value(text, key)
    assert _value(text, "FORCE_HTTPS_REDIRECTS") == "true"
    # Two runs never share a secret.
    assert _value(make_env.build(template, local=False), "SECRET_KEY") != _value(text, "SECRET_KEY")


def test_local_mode_turns_off_https_only():
    template = (make_env.ROOT / ".env.example").read_text(encoding="utf-8")
    text = make_env.build(template, local=True)
    assert _value(text, "FORCE_HTTPS_REDIRECTS") == "false"
    assert _value(text, "APP_ENV") == "development"


def test_never_overwrites_an_existing_env(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("SECRET_KEY=keep-me\n")
    (tmp_path / ".env.example").write_text("SECRET_KEY=x\n")
    monkeypatch.setattr(make_env, "ROOT", tmp_path)
    try:
        make_env.main([])
    except SystemExit as exc:
        assert "already exists" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("make_env overwrote an existing .env")
    assert (tmp_path / ".env").read_text() == "SECRET_KEY=keep-me\n"
