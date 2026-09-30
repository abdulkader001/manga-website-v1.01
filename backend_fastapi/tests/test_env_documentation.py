"""Guard against environment variables that code reads but nobody documents.

An undocumented variable is an operational trap: ``TRUSTED_PROXY_CIDRS``, for
instance, defines the client-IP trust boundary and has a default that is right
for docker-compose and wrong behind a cloud load balancer -- an operator who
never sees it in ``.env.example`` has no reason to look for it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "backend_fastapi" / "app"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

_GETENV = re.compile(r"""os\.(?:getenv|environ\.get)\(\s*['"]([A-Z][A-Z0-9_]*)['"]""")
_ENVIRON_ITEM = re.compile(r"""os\.environ\[\s*['"]([A-Z][A-Z0-9_]*)['"]""")
_SETTINGS_FIELD = re.compile(r"^\s{4}([a-z][a-z0-9_]*)\s*[:=]", re.MULTILINE)

# Attributes of the Settings class that are not configuration fields.
_NOT_SETTINGS_FIELDS = {"MODEL_CONFIG", "NORMALISED", "SUFFIX"}


def _documented() -> set[str]:
    return {
        line.split("=", 1)[0]
        for line in ENV_EXAMPLE.read_text().splitlines()
        if re.match(r"^[A-Z0-9_]+=", line)
    }


def _referenced() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in APP_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(errors="ignore")
        for pattern in (_GETENV, _ENVIRON_ITEM):
            for match in pattern.finditer(source):
                found.setdefault(match.group(1), str(path.relative_to(REPO_ROOT)))

    settings_source = (APP_ROOT / "core" / "settings.py").read_text()
    for match in _SETTINGS_FIELD.finditer(settings_source):
        name = match.group(1).upper()
        if name in _NOT_SETTINGS_FIELDS:
            continue
        found.setdefault(name, "backend_fastapi/app/core/settings.py")
    return found


def test_every_env_var_read_by_the_app_is_documented():
    documented = _documented()
    missing = {
        name: where for name, where in _referenced().items() if name not in documented
    }

    assert not missing, (
        "These environment variables are read by the application but absent "
        f"from .env.example: {sorted(missing)}. First reference: {missing}"
    )


def test_env_example_carries_no_live_values_for_the_operational_knobs():
    """Placeholders only -- .env.example is committed."""

    text = ENV_EXAMPLE.read_text()
    assert "TRUSTED_PROXY_CIDRS=" in text
    # The documented default must match the code's default, or the file is
    # actively misleading.
    from backend_fastapi.app.utils import client_ip

    documented = next(
        line.split("=", 1)[1]
        for line in text.splitlines()
        if line.startswith("TRUSTED_PROXY_CIDRS=")
    )
    assert documented == client_ip._DEFAULT_TRUSTED_PROXY_CIDRS


def test_gunicorn_timeout_exceeds_the_long_request_ceiling():
    """A worker must outlive the app's own deadline for exempt routes."""

    env = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in ENV_EXAMPLE.read_text().splitlines()
        if re.match(r"^[A-Z0-9_]+=", line)
    }
    assert int(env["GUNICORN_TIMEOUT"]) > int(env["LONG_REQUEST_TIMEOUT_SECONDS"])

    # And the shipped config default agrees, since GUNICORN_TIMEOUT is optional.
    namespace: dict[str, object] = {}
    exec(  # noqa: S102 - reading the config's computed values is the point
        (REPO_ROOT / "backend_fastapi" / "deployment" / "gunicorn.conf.py").read_text(),
        namespace,
    )
    long_timeout = float(os.getenv("LONG_REQUEST_TIMEOUT_SECONDS", "120"))
    assert namespace["timeout"] > long_timeout
