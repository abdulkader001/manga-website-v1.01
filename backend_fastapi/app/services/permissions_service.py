"""Effective-permission resolution and override management (SRS 1F.6–1F.10).

Resolution order (1F.10): never-grantable check -> explicit override -> role
default. Effective permission is resolved server-side on every request; there is
no client input to the decision. Overrides are stored per person; absence means
inherited.

The owner changes any sub-admin's overrides; a sub-admin holding
``manage_roles`` changes other sub-admins' everyday powers only
(``authorize_change``). Site-owner powers (``OWNER_POWERS``) are given and
taken by the owner alone, to at most ``MAX_DEPUTIES`` sub-admins who keep an
authenticator. Attempting to grant a never-grantable permission (1F.8) is
refused.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..core.permissions import (
    ALL_PERMISSIONS,
    BUILTIN_PRESETS,
    MAX_DEPUTIES,
    NEVER_GRANTABLE,
    OWNER_POWERS,
    builtin_presets,
    catalogue,
    effective_role,
    is_valid_permission,
    role_default,
)
from ..models import PermissionOverride, PermissionPreset, User, UserRole


def _overrides_for(db: Session, user_id: int) -> dict[str, str]:
    rows = (
        db.query(PermissionOverride).filter(PermissionOverride.user_id == user_id).all()
    )
    return {r.permission: r.state for r in rows}


def has_permission(db: Session, user: User, permission: str) -> bool:
    """Return the effective value of ``permission`` for ``user`` (1F.10)."""

    # Never-grantable capabilities are not permissions anyone can hold.
    if permission in NEVER_GRANTABLE or not is_valid_permission(permission):
        return False

    override = (
        db.query(PermissionOverride)
        .filter(
            PermissionOverride.user_id == user.id,
            PermissionOverride.permission == permission,
        )
        .first()
    )
    role = effective_role(user)
    # Three roles: a regular user never holds a catalogue (admin) permission,
    # whatever overrides exist, and the main admin always holds all of them.
    # Overrides only ever refine a sub-admin.
    if role == UserRole.USER:
        return False
    if role in (UserRole.ADMIN, UserRole.PERMANENT):
        return True
    if permission in OWNER_POWERS:
        # Only an explicit grant from the owner, and only while the holder
        # keeps an authenticator (a deputy who drops it is paused, not kept).
        return (
            override is not None
            and override.state == "granted"
            and bool(getattr(user, "totp_enabled", False))
        )

    if override is not None:
        return override.state == "granted"

    # F-4: resolve via effective_role, not the raw role column, so a flag-only
    # admin (is_main_admin/is_secondary_admin/permanent set without a
    # matching role) gets the same catalogue access require_admin_user's
    # role-tier gate already grants them.
    return role_default(permission, role)


def resolve_effective(db: Session, user: User) -> list[dict]:
    """The person's full effective permission set with state (1F.9.2)."""

    role = effective_role(user)
    # Same rule as has_permission: overrides only refine a sub-admin.
    overrides = _overrides_for(db, user.id) if role == UserRole.SECONDARY else {}
    out: list[dict] = []
    for key in ALL_PERMISSIONS:
        default = role_default(key, role)
        state = overrides.get(key)
        if key in OWNER_POWERS and state != "granted":
            state = None
        if state == "granted":
            effective, label = True, "granted"
            if key in OWNER_POWERS and not getattr(user, "totp_enabled", False):
                effective = False  # paused until they set up an authenticator
        elif state == "revoked":
            effective, label = False, "revoked"
        else:
            effective, label = default, "inherited"
        out.append(
            {
                "key": key,
                "effective": effective,
                "state": label,
                "role_default": default,
            }
        )
    return out


def modified_count(db: Session, user: User) -> int:
    return (
        db.query(PermissionOverride)
        .filter(PermissionOverride.user_id == user.id)
        .count()
    )


def _assert_sub_admin(target: User) -> None:
    if effective_role(target) != UserRole.SECONDARY:
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Only a sub-admin's permissions can be adjusted. Make the person a sub-admin first.",
            details={"reason": "not_a_sub_admin"},
        )


def _is_owner(user: User) -> bool:
    return effective_role(user) in (UserRole.ADMIN, UserRole.PERMANENT)


def deputy_ids(db: Session) -> set[int]:
    """Sub-admins holding at least one site-owner power (granted)."""

    rows = (
        db.query(PermissionOverride.user_id)
        .join(User, User.id == PermissionOverride.user_id)
        .filter(
            PermissionOverride.permission.in_(sorted(OWNER_POWERS)),
            PermissionOverride.state == "granted",
            User.role == UserRole.SECONDARY,
        )
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def is_deputy(db: Session, user: User) -> bool:
    return user.id in deputy_ids(db)


def _refuse(message: str, reason: str, **details) -> ApiError:
    return ApiError(ErrorCode.FORBIDDEN, message, details={"reason": reason, **details})


def authorize_change(db: Session, actor: User, target: User, grants: list[str]) -> None:
    """Who may change ``target``'s permissions, and grant ``grants``.

    * The owner: anyone but themselves (their own powers are fixed).
    * A sub-admin with ``manage_roles``: never themselves, never a deputy,
      never a site-owner power, and only powers they hold themselves.
    """

    if _is_owner(actor):
        return
    if target.id == actor.id:
        raise _refuse("You can't change your own permissions.", "self_change")
    if is_deputy(db, target):
        raise _refuse("Only the site owner can change a deputy's permissions.", "deputy_protected")
    for key in grants:
        if key in OWNER_POWERS:
            raise _refuse("Only the site owner can give site-owner powers.", "owner_only", permission=key)
        if not has_permission(db, actor, key):
            raise _refuse(f"You can't give '{key}': you don't hold it yourself.", "not_yours_to_give", permission=key)


def set_override(
    db: Session, target: User, permission: str, state: str, actor_id: int, *, by_owner: bool = False
) -> None:
    """Set or clear a single override (1F.6.2).

    ``state`` is 'granted', 'revoked', or 'inherited' (clears the override).
    Never-grantable permissions (1F.8) are refused, and only a sub-admin's
    permissions are adjustable (users hold none, the main admin holds all).
    Site-owner powers need ``by_owner`` (the caller checked the owner's
    authenticator code), an authenticator on the target, and a free deputy seat.
    """

    _assert_sub_admin(target)

    if permission in NEVER_GRANTABLE or not is_valid_permission(permission):
        raise ApiError(
            ErrorCode.FORBIDDEN,
            f"'{permission}' cannot be granted to anyone.",
            field="permission",
            details={"permission": permission, "reason": "never_grantable"},
        )
    if state not in ("granted", "revoked", "inherited"):
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "state must be granted, revoked, or inherited",
            field="state",
        )
    if permission in OWNER_POWERS:
        if not by_owner:
            raise _refuse("Only the site owner can give or take site-owner powers.", "owner_only", permission=permission)
        if state == "granted":
            if not getattr(target, "totp_enabled", False):
                raise _refuse(
                    "This sub-admin must set up an authenticator app (Admin -> Security) before holding site-owner powers.",
                    "authenticator_required",
                )
            others = deputy_ids(db) - {target.id}
            if len(others) >= MAX_DEPUTIES:
                raise _refuse(
                    f"Only {MAX_DEPUTIES} sub-admins can hold site-owner powers. Take them from one first.",
                    "deputy_limit",
                    limit=MAX_DEPUTIES,
                )
        else:
            # Off is the only other state: drop any stored row.
            state = "inherited"

    existing = (
        db.query(PermissionOverride)
        .filter(
            PermissionOverride.user_id == target.id,
            PermissionOverride.permission == permission,
        )
        .first()
    )

    if state == "inherited":
        if existing is not None:
            db.delete(existing)
        db.flush()
        return

    if existing is None:
        db.add(
            PermissionOverride(
                user_id=target.id,
                permission=permission,
                state=state,
                updated_by=actor_id,
            )
        )
    else:
        existing.state = state
        existing.updated_by = actor_id
    db.flush()


def clear_owner_powers(db: Session, target: User) -> int:
    """Take every site-owner power from ``target`` (demotion, succession)."""

    return (
        db.query(PermissionOverride)
        .filter(
            PermissionOverride.user_id == target.id,
            PermissionOverride.permission.in_(sorted(OWNER_POWERS)),
        )
        .delete(synchronize_session=False)
    )


def reset_to_default(db: Session, target: User, *, keep_owner_powers: bool = False) -> None:
    """Remove all overrides for a person (1F.9.2 reset-to-role-default)."""

    query = db.query(PermissionOverride).filter(PermissionOverride.user_id == target.id)
    if keep_owner_powers:
        query = query.filter(PermissionOverride.permission.notin_(sorted(OWNER_POWERS)))
    query.delete(synchronize_session=False)


def full_catalogue() -> list[dict]:
    return catalogue()


# --------------------------------------------------------------------------
# Presets (SRS 1F.9.3) and the "Modified only" list (SRS 1F.9.1)
# --------------------------------------------------------------------------


def list_presets(db: Session) -> list[dict]:
    """Built-in presets plus any custom ones created by the PA."""

    presets = builtin_presets()
    for row in db.query(PermissionPreset).order_by(PermissionPreset.key.asc()).all():
        definition = row.definition or {}
        presets.append(
            {
                "key": row.key,
                "label": row.label,
                "description": row.description,
                "grant": definition.get("grant", []),
                "revoke": definition.get("revoke", []),
                "builtin": False,
            }
        )
    return presets


def _resolve_preset(db: Session, preset_key: str) -> dict | None:
    if preset_key in BUILTIN_PRESETS:
        p = BUILTIN_PRESETS[preset_key]
        return {"grant": p["grant"], "revoke": p["revoke"]}
    row = db.query(PermissionPreset).filter(PermissionPreset.key == preset_key).first()
    if row is None:
        return None
    definition = row.definition or {}
    return {
        "grant": definition.get("grant", []),
        "revoke": definition.get("revoke", []),
    }


def apply_preset(db: Session, target: User, preset_key: str, actor_id: int) -> None:
    """Apply a preset: reset to role default, then set its explicit overrides.

    The result remains individually adjustable afterwards (SRS 1F.9.3). Any
    never-grantable/invalid key in the preset is skipped rather than failing the
    whole apply.
    """

    preset = _resolve_preset(db, preset_key)
    if preset is None:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            f"Unknown preset '{preset_key}'.",
            field="preset",
        )
    # A preset shapes everyday powers; site-owner powers are left as they are.
    reset_to_default(db, target, keep_owner_powers=True)
    for key in preset.get("revoke", []):
        if _presettable(key):
            set_override(db, target, key, "revoked", actor_id)
    for key in preset.get("grant", []):
        if _presettable(key):
            set_override(db, target, key, "granted", actor_id)


def _presettable(key: str) -> bool:
    """A key a preset may set on a sub-admin: a real catalogue permission that
    is neither never-grantable nor a site-owner power (those are skipped, so
    an older custom preset that lists them still applies)."""

    return is_valid_permission(key) and key not in NEVER_GRANTABLE and key not in OWNER_POWERS


def create_custom_preset(
    db: Session,
    *,
    key: str,
    label: str,
    description: str | None,
    grant: list[str],
    revoke: list[str],
    actor_id: int,
) -> PermissionPreset:
    """Persist a custom preset (PA only). Drops invalid, never-grantable and
    site-owner-power keys."""

    key = (key or "").strip().lower()
    if not key or key in BUILTIN_PRESETS:
        raise ApiError(
            ErrorCode.VALIDATION_FAILED, "Invalid or reserved preset key.", field="key"
        )
    clean_grant = [k for k in grant if _presettable(k)]
    clean_revoke = [k for k in revoke if _presettable(k)]
    existing = db.query(PermissionPreset).filter(PermissionPreset.key == key).first()
    definition = {"grant": clean_grant, "revoke": clean_revoke}
    if existing is not None:
        existing.label = label
        existing.description = description
        existing.definition = definition
        return existing
    preset = PermissionPreset(
        key=key,
        label=label,
        description=description,
        definition=definition,
        created_by=actor_id,
    )
    db.add(preset)
    return preset


def list_managed_people(db: Session, *, modified_only: bool = False) -> list[dict]:
    """Sub-admins with their modified count.

    Powers the Role & Permission Management list and its "Modified only" filter
    (SRS 1F.9.1).
    """

    rows = (
        db.query(User)
        .filter(User.role == UserRole.SECONDARY)
        .order_by(User.id.asc())
        .all()
    )
    out: list[dict] = []
    deputies = deputy_ids(db)
    for user in rows:
        count = modified_count(db, user)
        if modified_only and count == 0:
            continue
        out.append(
            {
                "user_id": user.id,
                "name": getattr(user, "name", None),
                "role": user.role.value if user.role else None,
                "modified_count": count,
                "deputy": user.id in deputies,
                "authenticator": bool(getattr(user, "totp_enabled", False)),
            }
        )
    return out
