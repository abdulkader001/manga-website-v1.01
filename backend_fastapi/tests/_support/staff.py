"""People and headers for tests of the owner / Admin / sub-admin tiers."""

from __future__ import annotations

import random
import uuid

from backend_fastapi.app.core.db import SessionLocal
from backend_fastapi.app.core.security import create_access_token
from backend_fastapi.app.models import AdminSuccessor, User, UserRole
from backend_fastapi.app.services import admin_second_factor as tfa
from backend_fastapi.app.services.system_settings_service import get_or_create_system_settings


def make_user(role: UserRole, *, main=False, authenticator=False, active=True) -> int:
    with SessionLocal() as session:
        user = User(
            # A fresh, large id: SQLite reuses ids of users other tests deleted,
            # and the (append-only) audit log keeps their rows.
            id=random.randint(10**8, 2 * 10**9),
            email=f"st-{uuid.uuid4().hex}@example.com",
            is_active=active,
            name=f"{role.value}-{uuid.uuid4().hex[:4]}",
            role=role,
            is_main_admin=main,
            is_secondary_admin=role in (UserRole.SECONDARY, UserRole.CO_ADMIN),
            provider="magic_link",
        )
        session.add(user)
        session.commit()
        if authenticator:
            tfa.start_enrolment(session, user)
            user.totp_enabled = True
            session.commit()
        return user.id


def owner() -> int:
    return make_user(UserRole.ADMIN, main=True, authenticator=True)


def admin() -> int:
    return make_user(UserRole.CO_ADMIN, authenticator=True)


def sub_admin() -> int:
    return make_user(UserRole.SECONDARY, authenticator=True)


def reader() -> int:
    return make_user(UserRole.USER)


def code(uid: int) -> str:
    with SessionLocal() as session:
        user = session.get(User, uid)
        user.totp_last_step = None
        session.commit()
        return tfa._code_for_step(tfa._stored_secret(user), tfa._current_step())


def headers(uid: int, *, step_up: bool = True) -> dict:
    out = {"Authorization": f"Bearer {create_access_token(str(uid))}"}
    if step_up:
        with SessionLocal() as session:
            token = tfa.create_step_up_token(session.get(User, uid))
        out["Cookie"] = f"{tfa.STEP_UP_COOKIE}={token}"
    return out


def reset_staff() -> None:
    """Admin seats are site-wide: leave none behind."""

    with SessionLocal() as session:
        session.query(AdminSuccessor).delete()
        session.query(User).filter(User.role == UserRole.CO_ADMIN).update(
            {"role": UserRole.USER, "is_secondary_admin": False, "visible_admin_tabs": None, "powers_suspended": False}
        )
        row = get_or_create_system_settings(session)
        row.sub_admin_blocked_permissions = None
        session.commit()
