"""Effective-permission resolution and override management (SRS 1F.6–1F.10).

Resolution order (1F.10): never-grantable check -> explicit override -> role
default. Effective permission is resolved server-side on every request; there is
no client input to the decision. Overrides are stored per person; absence means
inherited.

Only the Permanent Administrator may change overrides (enforced at the API
layer). Attempting to grant a never-grantable permission (1F.8) is refused.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..core.permissions import (
    ALL_PERMISSIONS,
    BUILTIN_PRESETS,
    MAIN_ADMIN_ONLY,
    NEVER_GRANTABLE,
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
    if permission in MAIN_ADMIN_ONLY:
        # Main admin only: an override stored before this rule (or written
        # straight into the table) never gives it to a sub-admin.
        return False

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
        if key in MAIN_ADMIN_ONLY:
            # Never held by a sub-admin, whatever is stored (has_permission).
            state = None
        if state == "granted":
            effective, label = True, "granted"
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


def set_override(
    db: Session, target: User, permission: str, state: str, actor_id: int
) -> None:
    """Set or clear a single override (1F.6.2).

    ``state`` is 'granted', 'revoked', or 'inherited' (clears the override).
    Never-grantable permissions (1F.8) are refused, and only a sub-admin's
    permissions are adjustable (users hold none, the main admin holds all).
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
    if permission in MAIN_ADMIN_ONLY:
        if state == "granted":
            raise ApiError(
                ErrorCode.FORBIDDEN,
                "The Scraper AI (its API key and Custom Parser) is main-admin only "
                "and cannot be given to a sub-admin.",
                field="permission",
                details={"permission": permission, "reason": "main_admin_only"},
            )
        # Revoking is already the only possible state: drop any stored row.
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


def reset_to_default(db: Session, target: User) -> None:
    """Remove all overrides for a person (1F.9.2 reset-to-role-default)."""

    db.query(PermissionOverride).filter(PermissionOverride.user_id == target.id).delete(
        synchronize_session=False
    )


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
    reset_to_default(db, target)
    for key in preset.get("revoke", []):
        if _presettable(key):
            set_override(db, target, key, "revoked", actor_id)
    for key in preset.get("grant", []):
        if _presettable(key):
            set_override(db, target, key, "granted", actor_id)


def _presettable(key: str) -> bool:
    """A key a preset may set on a sub-admin: a real catalogue permission that
    is neither never-grantable nor main-admin only (those are skipped, so an
    older custom preset that lists them still applies)."""

    return is_valid_permission(key) and key not in NEVER_GRANTABLE and key not in MAIN_ADMIN_ONLY


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
    main-admin-only keys."""

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
            }
        )
    return out
