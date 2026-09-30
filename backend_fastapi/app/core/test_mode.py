"""Central guard for test-only conveniences.

A test flag on its own is **never** sufficient to enable behaviour that
returns a credential, disables a rate limit, or bypasses the broker. Every
such convenience must also confirm the process is *not* running in
production, mirroring the pattern already used by
``app/utils/crypto_utils.py`` (see ``allow_plaintext_fallback``): check the
explicit deployment environment, not just the raw flag.

All helpers read the environment live (per call) rather than caching at
import, so they behave correctly regardless of when a flag is set.
"""

from __future__ import annotations

import os

# Deployment-environment values that mean "production". Anything here is a
# hard no for test-mode conveniences, regardless of any flag.
_PRODUCTION_ENVIRONMENTS = {"production", "prod"}

_TRUTHY = {"1", "true", "yes", "on"}

# Operator-set env flags that grant test-only behaviour. If any of these is
# truthy while the environment is production we refuse to start (see
# ``assert_test_flags_safe``). ``PYTEST_CURRENT_TEST`` is deliberately NOT
# treated as an enabler here: it is set automatically by pytest for every test,
# so keying test-mode off it would stop a test from turning the flag *off* to
# exercise the real (non-test) code path. ``TESTING`` is the codebase's
# canonical, operator-controlled test flag.
_TEST_FLAG_ENV_VARS = ("TESTING", "CELERY_TASK_ALWAYS_EAGER")


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in _TRUTHY)


def current_environment() -> str:
    """Return the normalised deployment environment (``APP_ENV``/``ENVIRONMENT``)."""

    return (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()


def is_production() -> bool:
    """True when the deployment environment is production."""

    return current_environment() in _PRODUCTION_ENVIRONMENTS


def enabled_test_flags() -> list[str]:
    """Names of test-mode env flags currently set to a truthy value."""

    return [name for name in _TEST_FLAG_ENV_VARS if _truthy(os.getenv(name))]


def test_mode_active() -> bool:
    """Whether test-only request conveniences may be honoured.

    Returns True only when a test flag is set **and** the deployment is not
    production. This is the single gate for behaviour like returning a magic
    link's debug token or skipping a rate limit — never gate such behaviour
    on ``os.getenv("TESTING")`` alone.
    """

    if is_production():
        return False
    return _truthy(os.getenv("TESTING"))


def celery_eager_active() -> bool:
    """Whether Celery should run tasks inline (eager) instead of via a broker.

    Only honoured outside production, so a stray ``CELERY_TASK_ALWAYS_EAGER``
    in a production deploy cannot silently bypass the worker fleet.
    """

    return not is_production() and _truthy(os.getenv("CELERY_TASK_ALWAYS_EAGER"))


def assert_test_flags_safe() -> None:
    """Refuse to start when production is combined with any test-mode flag.

    Called at settings construction (i.e. process startup for web, worker and
    beat) so a misconfigured production deploy fails loudly instead of
    silently serving requests with test-mode behaviour active.
    """

    if not is_production():
        return
    flags = enabled_test_flags()
    if flags:
        raise RuntimeError(
            "Refusing to start: production environment (APP_ENV="
            f"{current_environment()!r}) with test-mode flags set: "
            f"{', '.join(flags)}. These flags return live credentials, disable "
            "rate limits, or bypass the Celery broker and must never be set in "
            "production."
        )


__all__ = [
    "assert_test_flags_safe",
    "celery_eager_active",
    "current_environment",
    "enabled_test_flags",
    "is_production",
    "test_mode_active",
]
