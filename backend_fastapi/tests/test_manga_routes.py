from __future__ import annotations


def test_manga_browse_routes_are_equivalent(fastapi_client, sample_data):
    """Both /manga/ and /manga/browse should return identical payloads."""

    params = {"page": 1, "per_page": 5}
    primary = fastapi_client.get("/api/manga/", params=params)
    legacy = fastapi_client.get("/api/manga/browse", params=params)

    assert primary.status_code == 200
    assert legacy.status_code == 200
    assert primary.json() == legacy.json()
