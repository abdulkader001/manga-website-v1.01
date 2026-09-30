"""Load-test script encoding the realistic traffic mix (item 44a).

Traffic mix (task weights approximate the target distribution):
  ~80% reads      — manga list/detail/chapters, config, system state
  ~15% auth/session — magic-link request, auth options, refresh
  ~5%  writes     — bookmarks / read-history (require a bearer token)

Run locally against the dev stack (won't reach 100k on a laptop — that's the
human-executed runbook item 44b):

    pip install locust
    locust -f backend_fastapi/loadtest/locustfile.py --host http://localhost:8000

Headless, ramped example:

    locust -f backend_fastapi/loadtest/locustfile.py --host http://localhost:8000 \\
        --headless -u 500 -r 50 -t 5m

Provide a bearer token for the write/authenticated tasks via LOADTEST_TOKEN so
the 5% write slice exercises real authenticated paths:

    LOADTEST_TOKEN=<access-token> locust -f ... --host ...
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, task

_TOKEN = os.getenv("LOADTEST_TOKEN", "")
_AUTH_HEADERS = {"Authorization": f"Bearer {_TOKEN}"} if _TOKEN else {}

# A small pool of manga ids to read; override with real ids from a seeded DB.
_MANGA_IDS = [int(x) for x in os.getenv("LOADTEST_MANGA_IDS", "1,2,3,4,5").split(",")]


class MangaReader(HttpUser):
    """Simulates a typical anonymous-to-logged-in reader."""

    wait_time = between(0.5, 3.0)

    # ---- reads (~80%) ----

    @task(40)
    def browse_list(self):
        params = {
            "page": random.randint(1, 5),
            "per_page": 60,
            "sort": random.choice(["latest", "new", "views"]),
        }
        self.client.get("/api/manga/", params=params, name="/api/manga [list]")

    @task(20)
    def manga_detail(self):
        mid = random.choice(_MANGA_IDS)
        self.client.get(f"/api/manga/{mid}", name="/api/manga/{id}")

    @task(12)
    def chapter_list(self):
        mid = random.choice(_MANGA_IDS)
        self.client.get(f"/api/manga/{mid}/chapters", name="/api/manga/{id}/chapters")

    @task(4)
    def search(self):
        q = random.choice(["a", "the", "one", "love", "war"])
        self.client.get("/api/manga/", params={"q": q}, name="/api/manga [search]")

    @task(4)
    def config_and_state(self):
        self.client.get("/api/system/state", name="/api/system/state")

    # ---- auth / session (~15%) ----

    @task(10)
    def auth_options(self):
        self.client.get("/api/auth/options", name="/api/auth/options")

    @task(5)
    def request_magic_link(self):
        email = f"loadtest+{random.randint(1, 100000)}@example.com"
        self.client.post(
            "/api/auth/request-magic-link",
            json={"email": email},
            name="/api/auth/request-magic-link",
        )

    # ---- writes (~5%, require a token) ----

    @task(5)
    def write_bookmark(self):
        if not _AUTH_HEADERS:
            return  # skip writes when no token is configured
        mid = random.choice(_MANGA_IDS)
        self.client.post(
            "/api/bookmarks",
            json={"manga_id": mid},
            headers=_AUTH_HEADERS,
            name="/api/bookmarks [write]",
        )
