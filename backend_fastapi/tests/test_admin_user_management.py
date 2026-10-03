from __future__ import annotations

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.models import SystemState, User, UserRole
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.services.system_state import get_or_create_system_state
from _support.db_reset import clear_users


def _reset_users(session: SessionLocal) -> None:
    clear_users(session)


def _reset_system_state(session: SessionLocal) -> None:
    session.query(SystemState).delete()
    session.commit()


def _create_user(**overrides) -> User:
    defaults = {
        "email": overrides.get("email", "user@example.com"),
        "is_active": True,
        "name": overrides.get("name", "User"),
        "username": overrides.get("username"),
        "role": overrides.get("role", UserRole.USER),
        "is_main_admin": overrides.get("is_main_admin", False),
        "is_secondary_admin": overrides.get("is_secondary_admin", False),
        "provider": "magic_link",
    }
    return User(**defaults)


def test_users_all_alias_returns_full_listing(fastapi_client):
    session = SessionLocal()
    try:
        _reset_users(session)

        admin = _create_user(
            email="admin@example.com",
            name="Admin",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=True,
            username="admin",
        )
        member = _create_user(email="member@example.com", name="Member")
        session.add_all([admin, member])
        session.commit()
        session.refresh(admin)
        session.refresh(member)
        admin_id = admin.id
        member_id = member.id
    finally:
        session.close()

    admin_token = create_access_token(str(admin_id))
    headers = {"Authorization": f"Bearer {admin_token}"}

    resp = fastapi_client.get("/api/admin/users/all", headers=headers)
    assert resp.status_code == 200
    users = resp.json()
    assert {user["id"] for user in users} == {admin_id, member_id}
    assert all("email" in user for user in users)

    member_token = create_access_token(str(member_id))
    member_headers = {"Authorization": f"Bearer {member_token}"}
    forbidden = fastapi_client.get("/api/admin/users/all", headers=member_headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["message"] == "You do not have permission to perform this action."


def test_list_users_supports_pagination_and_search(fastapi_client):
    session = SessionLocal()
    try:
        _reset_users(session)

        admin = _create_user(
            email="admin@example.com",
            name="Admin",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=True,
            username="admin",
        )
        session.add(admin)
        session.commit()
        session.refresh(admin)
        admin_id = admin.id

        batch: list[User] = []
        for idx in range(25):
            batch.append(
                _create_user(
                    email=f"member{idx}@example.com",
                    name=f"Member {idx}",
                    username=f"member{idx}",
                )
            )
        special = _create_user(
            email="special@example.com",
            name="Special Person",
            username="UniqueHero",
        )
        batch.append(special)
        session.add_all(batch)
        session.commit()
        session.refresh(special)
        special_id = special.id
    finally:
        session.close()

    headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}

    resp = fastapi_client.get(
        "/api/admin/users",
        headers=headers,
        params={"page": 2, "per_page": 10},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["page"] == 2
    assert payload["per_page"] == 10
    assert payload["pages"] == 3
    assert payload["total"] == 27
    assert payload["has_next"] is True
    assert payload["has_prev"] is True
    assert len(payload["items"]) == 10
    assert all("id" in entry for entry in payload["items"])

    search_resp = fastapi_client.get(
        "/api/admin/users",
        headers=headers,
        params={"search": "UNIQUEHERO"},
    )
    assert search_resp.status_code == 200
    search_payload = search_resp.json()
    assert search_payload["page"] == 1
    assert search_payload["per_page"] == 20
    assert search_payload["pages"] == 1
    assert search_payload["total"] == 1
    assert search_payload["has_next"] is False
    assert search_payload["has_prev"] is False
    assert len(search_payload["items"]) == 1
    assert search_payload["items"][0]["id"] == special_id
    assert search_payload["items"][0]["username"] == "UniqueHero"


def test_demote_main_admin_successfully_updates_flags_and_state(fastapi_client):
    session = SessionLocal()
    try:
        _reset_system_state(session)
        _reset_users(session)

        actor = _create_user(
            email="actor@example.com",
            name="Actor",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=True,
        )
        target = _create_user(
            email="target@example.com",
            name="Target",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=False,
        )
        session.add_all([actor, target])
        session.commit()
        session.refresh(actor)
        session.refresh(target)

        state = get_or_create_system_state(session, for_update=True)
        state.main_admin_email = target.email
        session.commit()
        actor_id = actor.id
        target_id = target.id
    finally:
        session.close()

    token = create_access_token(str(actor_id))
    headers = {"Authorization": f"Bearer {token}"}

    resp = fastapi_client.post(
        "/api/admin/demote-main",
        headers=headers,
        json={"user_id": target_id},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["user"]["is_main_admin"] is False
    assert payload["user"]["role"] == UserRole.USER.value

    session = SessionLocal()
    try:
        refreshed = session.get(User, target_id)
        assert refreshed is not None
        assert refreshed.is_main_admin is False
        assert refreshed.role == UserRole.USER

        state = get_or_create_system_state(session)
        assert state.main_admin_email is None
    finally:
        session.close()


def test_demote_main_admin_refuses_against_permanent_target(fastapi_client):
    """F-64: a different top-tier (is_main_admin) account must not be able to
    demote the real Permanent Administrator. The action is refused outright
    (403, permanent_admin_immutable) -- not a silent partial update that
    flips is_main_admin off while leaving role/permanent untouched."""

    session = SessionLocal()
    try:
        _reset_system_state(session)
        _reset_users(session)

        actor = _create_user(
            email="other-top-tier@example.com",
            name="Actor",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=True,
        )
        target = _create_user(
            email="owner@example.com",
            name="Owner",
            role=UserRole.PERMANENT,
            is_main_admin=True,
            is_secondary_admin=True,
        )
        target.permanent = True
        session.add_all([actor, target])
        session.commit()
        session.refresh(actor)
        session.refresh(target)

        state = get_or_create_system_state(session, for_update=True)
        state.main_admin_email = target.email
        session.commit()
        actor_id = actor.id
        target_id = target.id
        target_email = target.email
    finally:
        session.close()

    token = create_access_token(str(actor_id))
    headers = {"Authorization": f"Bearer {token}"}

    resp = fastapi_client.post(
        "/api/admin/demote-main",
        headers=headers,
        json={"user_id": target_id},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["details"]["reason"] == "permanent_admin_immutable"

    session = SessionLocal()
    try:
        refreshed = session.get(User, target_id)
        assert refreshed is not None
        # Refused outright -- neither field moved, so they stay in sync.
        assert refreshed.is_main_admin is True
        assert refreshed.role == UserRole.PERMANENT
        assert refreshed.permanent is True

        state = get_or_create_system_state(session)
        assert state.main_admin_email == target_email
    finally:
        session.close()


def test_demote_main_admin_rejects_self_demotions(fastapi_client):
    session = SessionLocal()
    try:
        _reset_system_state(session)
        _reset_users(session)

        actor = _create_user(
            email="self@example.com",
            name="Self",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=True,
        )
        session.add(actor)
        session.commit()
        session.refresh(actor)

        state = get_or_create_system_state(session, for_update=True)
        state.main_admin_email = actor.email
        session.commit()
        actor_id = actor.id
    finally:
        session.close()

    token = create_access_token(str(actor_id))
    headers = {"Authorization": f"Bearer {token}"}

    resp = fastapi_client.post(
        "/api/admin/demote-main",
        headers=headers,
        json={"user_id": actor_id},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "Main admin cannot demote themselves."


def test_admin_status_rejects_non_admins(fastapi_client):
    """Blind Spot #13: /admin/status must not be probeable by non-admins."""

    session = SessionLocal()
    try:
        _reset_users(session)
        member = _create_user(email="member@example.com", name="Member")
        admin = _create_user(
            email="admin@example.com",
            name="Admin",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=True,
            username="admin",
        )
        session.add_all([member, admin])
        session.commit()
        session.refresh(member)
        session.refresh(admin)
        member_id = member.id
        admin_id = admin.id
    finally:
        session.close()

    member_headers = {"Authorization": f"Bearer {create_access_token(str(member_id))}"}
    forbidden = fastapi_client.get("/api/admin/status", headers=member_headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["message"] == "Admin privileges required"

    admin_headers = {"Authorization": f"Bearer {create_access_token(str(admin_id))}"}
    allowed = fastapi_client.get("/api/admin/status", headers=admin_headers)
    assert allowed.status_code == 200
    assert allowed.json()["authenticated"] is True


def test_no_api_route_assigns_permanent_admin(fastapi_client):
    """SRS 1F.2.4: no API endpoint assigns the Permanent Administrator role.

    Not a hidden one, not an admin-only one, not one behind a feature flag.
    The old POST /admin/permanent/{id} escalation path is removed entirely, so
    it returns 404 for every caller — a secondary admin AND a main admin — and
    the target's role is untouched.
    """

    session = SessionLocal()
    try:
        _reset_system_state(session)
        _reset_users(session)

        secondary = _create_user(
            email="secondary@example.com",
            name="Secondary",
            role=UserRole.SECONDARY,
            is_secondary_admin=True,
            username="secondary",
        )
        main_admin = _create_user(
            email="main@example.com",
            name="Main",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=True,
            username="main",
        )
        target = _create_user(
            email="target@example.com",
            name="Target",
            username="target",
        )
        session.add_all([secondary, main_admin, target])
        session.commit()
        session.refresh(secondary)
        session.refresh(main_admin)
        session.refresh(target)
        secondary_id = secondary.id
        main_id = main_admin.id
        target_id = target.id
    finally:
        session.close()

    for actor_id in (secondary_id, main_id):
        headers = {"Authorization": f"Bearer {create_access_token(str(actor_id))}"}
        resp = fastapi_client.post(f"/api/admin/permanent/{target_id}", headers=headers)
        assert resp.status_code == 404

    # The target must not have been promoted by any request.
    session = SessionLocal()
    try:
        refreshed = session.get(User, target_id)
        assert refreshed is not None
        assert refreshed.is_main_admin is False
        assert refreshed.role == UserRole.USER
    finally:
        session.close()


def test_reveal_user_email_rejects_secondary_admins(fastapi_client):
    """H4: unmasked PII reveal must be restricted to main admins."""

    session = SessionLocal()
    try:
        _reset_system_state(session)
        _reset_users(session)

        secondary = _create_user(
            email="secondary@example.com",
            name="Secondary",
            role=UserRole.SECONDARY,
            is_secondary_admin=True,
            username="secondary",
        )
        main_admin = _create_user(
            email="main@example.com",
            name="Main",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=True,
            username="main",
        )
        target = _create_user(
            email="target@example.com",
            name="Target",
            username="target",
        )
        session.add_all([secondary, main_admin, target])
        session.commit()
        session.refresh(secondary)
        session.refresh(main_admin)
        session.refresh(target)
        secondary_id = secondary.id
        main_id = main_admin.id
        target_id = target.id
    finally:
        session.close()

    secondary_headers = {
        "Authorization": f"Bearer {create_access_token(str(secondary_id))}"
    }
    forbidden = fastapi_client.get(
        f"/api/admin/users/{target_id}/email", headers=secondary_headers
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["details"]["reason"] == "missing_power"

    main_headers = {"Authorization": f"Bearer {create_access_token(str(main_id))}"}
    allowed = fastapi_client.get(
        f"/api/admin/users/{target_id}/email", headers=main_headers
    )
    assert allowed.status_code == 200
    assert allowed.json()["user_id"] == target_id


def test_demote_main_admin_requires_main_admin_privileges(fastapi_client):
    session = SessionLocal()
    try:
        _reset_system_state(session)
        _reset_users(session)

        main_admin = _create_user(
            email="main@example.com",
            name="Main",
            role=UserRole.ADMIN,
            is_main_admin=True,
            is_secondary_admin=True,
        )
        secondary = _create_user(
            email="secondary@example.com",
            name="Secondary",
            role=UserRole.SECONDARY,
            is_secondary_admin=True,
        )
        session.add_all([main_admin, secondary])
        session.commit()
        session.refresh(main_admin)
        session.refresh(secondary)
        main_id = main_admin.id
        secondary_id = secondary.id
    finally:
        session.close()

    token = create_access_token(str(secondary_id))
    headers = {"Authorization": f"Bearer {token}"}

    resp = fastapi_client.post(
        "/api/admin/demote-main",
        headers=headers,
        json={"user_id": main_id},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["message"] == "Main admin privileges required"
