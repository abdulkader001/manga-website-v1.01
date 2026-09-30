#!/usr/bin/env python
"""Container healthcheck for the Celery worker and beat services.

Both compose services used to curl the *backend's* ``/healthz``, which reports
on a different container entirely: a worker that had crashed, deadlocked, or
was killed still looked healthy for as long as the API was up. This ports the
two checks the k8s manifests already perform (``backend_fastapi/deployment/k8s/celery-worker.yaml``)
into a single exit-code contract compose can use:

1. the broker is reachable from *this* container (readiness), and
2. a matching ``celery worker``/``celery beat`` process is actually running in
   this container's PID namespace (liveness).

The process check reads ``/proc`` directly rather than shelling out to
``pgrep``: the runtime image is ``python:3.11-slim``, which does not ship
procps, so a ``pgrep``-based test would fail open or fail closed for the wrong
reason.

Usage: ``python celery_healthcheck.py {worker,beat}``
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROLE_MARKERS = {
    # ``celery -A ... worker`` / ``... beat``: match the subcommand token so a
    # stale shell wrapper in the same container is not mistaken for the daemon.
    "worker": "worker",
    "beat": "beat",
}


def _process_cmdlines():
    """Yield the argv of every process visible here, except our own."""

    own_pid = os.getpid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == own_pid:
            # Skipping ourselves matters: this script's own command line is
            # "python .../celery_healthcheck.py worker", which would otherwise
            # satisfy the check below and make it always report healthy.
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            # The process exited between listdir and read, or is not ours.
            continue
        if not raw:
            continue
        yield [part.decode("utf-8", "replace") for part in raw.split(b"\x00") if part]


def _is_celery_invocation(argv: list[str]) -> bool:
    """True for a real celery launch, and not for anything looser.

    Three shapes count. ``celery`` is a Python console script, so the kernel
    reports it via its shebang interpreter -- ``['/usr/bin/python3',
    '/usr/local/bin/celery', 'worker', ...]`` -- which is why argv[1] is
    inspected as well as argv[0]:

    * ``celery ... worker``
    * ``/usr/bin/python3 /usr/local/bin/celery ... worker``
    * ``python -m celery ... worker``

    A substring match on "celery" anywhere in argv would be looser than this
    and would match, among other things, this script's own command line.
    """

    if not argv:
        return False
    if any(os.path.basename(arg) == "celery" for arg in argv[:2]):
        return True
    if "-m" in argv:
        module_index = argv.index("-m") + 1
        return argv[module_index : module_index + 1] == ["celery"]
    return False


def _celery_process_running(role: str) -> bool:
    marker = _ROLE_MARKERS[role]
    for argv in _process_cmdlines():
        if _is_celery_invocation(argv) and marker in argv:
            return True
    return False


def _broker_reachable() -> bool:
    url = os.environ.get("CELERY_BROKER_URL") or os.environ.get("REDIS_URL")
    if not url:
        return False
    try:
        from redis import Redis
    except ImportError:
        return False
    try:
        client = Redis.from_url(url, socket_connect_timeout=3, socket_timeout=3)
        client.ping()
    except Exception:
        return False
    return True


def main(argv: list[str]) -> int:
    role = argv[1] if len(argv) > 1 else "worker"
    if role not in _ROLE_MARKERS:
        print(f"unknown role {role!r}; expected one of {sorted(_ROLE_MARKERS)}")
        return 2

    if not _celery_process_running(role):
        print(f"no running 'celery {role}' process in this container")
        return 1

    if not _broker_reachable():
        print("celery broker is not reachable")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
