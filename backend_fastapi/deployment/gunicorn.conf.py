"""Gunicorn configuration for the Manga backend.

Calculates the number of worker processes using the commonly recommended
formula ``workers = 2 * cpu_count + 1``. The value can be overridden via the
``GUNICORN_WORKERS`` environment variable if necessary (for example to limit
resource usage on small hosts).
"""

from __future__ import annotations

import multiprocessing
import os
from typing import Optional


def _get_int_env(name: str, default: int) -> int:
    """Fetch an integer from the environment, falling back to ``default``."""
    raw: Optional[str] = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Environment variable {name} must be an integer, got {raw!r}")


_default_workers = 2 * multiprocessing.cpu_count() + 1
workers = _get_int_env("GUNICORN_WORKERS", _default_workers)

# Bind/Logging configuration.
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# ``backend_fastapi/deployment/logging.conf`` writes to /var/log/manga, which only exists on hosts
# provisioned by backend_fastapi/deployment/setup-server.sh -- inside the container the app runs as
# the unprivileged ``appuser`` and cannot create it, and gunicorn aborts at
# startup when a logconfig references an unwritable handler. Default to
# gunicorn's own stdout/stderr logging and let operators opt in explicitly.
logconfig = os.getenv("GUNICORN_LOG_CONFIG") or None

# Ensure Gunicorn is aware of where to write its PID for process managers that
# rely on it. Defaults to /tmp because the container user cannot write /var/run;
# host installs that want the classic location set ``GUNICORN_PIDFILE``.
#
# NOT ``GUNICORN_PID``: that name is reserved by gunicorn's arbiter, which sets
# it to the master PID across a re-exec and parses it back with
# ``int(os.environ['GUNICORN_PID'])`` on startup. Pointing it at a path made
# every boot die with "ValueError: invalid literal for int() with base 10:
# '/tmp/gunicorn.pid'" before a single worker started.
pidfile = os.getenv("GUNICORN_PIDFILE", "/tmp/gunicorn.pid")

# Allow tweaking the worker class as needed (e.g. gevent). Defaults to sync.
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "uvicorn.workers.UvicornWorker")

# Forward access/error logs to stdout/stderr unless overridden. Docker captures
# these by default, making it easier to collect logs centrally.
accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")

# Worker heartbeat ceiling. This must stay ABOVE the application's own
# ``LONG_REQUEST_TIMEOUT_SECONDS`` (120s by default, the ceiling
# ``TimeoutMiddleware`` grants exempt OCR/translation routes), otherwise
# gunicorn kills the worker mid-request and the caller sees a dropped
# connection instead of the application's own 504. 180s leaves headroom for
# the response to be written after the app-level deadline is reached.
timeout = _get_int_env("GUNICORN_TIMEOUT", 180)

# Give in-flight requests the same headroom to finish during a rolling restart
# instead of being SIGKILLed after gunicorn's 30s default.
graceful_timeout = _get_int_env("GUNICORN_GRACEFUL_TIMEOUT", timeout)
