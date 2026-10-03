"""Effective-permission resolution and override management (SRS 1F.6–1F.10).

Resolution order (1F.10): never-grantable check -> explicit override -> role
default. Effective permission is resolved server-side on every request; there is
no client input to the decision. Overrides are stored per person; absence means
inherited.

Four roles (owner's rules, 2026-10-02): the owner holds everything and changes
anyone's toggles (never their own). An Admin holds almost everything by
default; only the owner changes an Admin's toggles. An Admin changes
sub-admins' toggles: never their own, never another Admin's, never a
site-owner power, never one the owner's ceiling blocks, and only powers they
hold themselves. Attempting to grant a never-grantable permission (1F.8) is
refused.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.api_errors import ApiError, ErrorCode
from ..core.admin_tabs import tabs_of
from ..core.permissions import (
    ALL_PERMISSIONS,
    BUILTIN_PRESETS,
    NEVER_GRANTABLE,
    OWNER_POWERS,
    OWNER_ROLES,
    builtin_presets,
    catalogue,
    effective_role,
    is_valid_permission,
    rank,
    role_default,
)
from ..models import PermissionOverride, PermissionPreset, User, UserRole

ADJUSTABLE = (UserRole.SECONDARY, UserRole.CO_ADMIN)


def _overrides_for(db: Session, user_id: int) -> dict[str, str]:
    rows = (
        db.query(PermissionOverride).filter(PermissionOverride.user_id == user_id).all()
    )
    return {r.permission: r.state for r in rows}


def sub_admin_blocked(db: Session) -> set[str]:
    """The owner's ceiling: permissions no sub-admin can hold."""

    from .system_settings_service import get_or_create_system_settings

    raw = get_or_create_system_settings(db).sub_admin_blocked_permissions or []
    return {key for key in raw if is_valid_permission(key)}


def _owner_restriction(user: User, key: str) -> str | None:
    """Why the owner's switches take ``key`` away from this person, if they do:
    "suspended" (all powers switched off) or "tab_hidden" (the permission belongs
    to an admin tab the owner left off their tab list)."""

    if getattr(user, "powers_suspended", False):
        return "suspended"
    tabs = getattr(user, "visible_admin_tabs", None)
    if tabs is not None:
        belongs_to = tabs_of(key)
        if belongs_to and not any(tab in tabs for tab in belongs_to):
            return "tab_hidden"
    return None


def _decide(user: User, role: UserRole, key: str, state: str | None, blocked: set[str]) -> tuple[bool, str]:
    """(effective, label) for ``key``: the one rule both ``has_permission`` and
    the toggle page use, so they can't disagree."""

    if role in OWNER_ROLES:
        return True, "inherited"
    if role not in ADJUSTABLE:
        return False, "inherited"
    hidden = _owner_restriction(user, key)
    if hidden:
        return False, hidden
    if role == UserRole.SECONDARY:
        if key in OWNER_POWERS:
            return False, "inherited"  # a sub-admin never holds a site-owner power
        if key in blocked:
            return False, "blocked"  # the owner's ceiling
    if state == "granted":
        effective, label = True, "granted"
    elif state == "revoked":
        effective, label = False, "revoked"
    else:
        effective, label = role_default(key, role), "inherited"
    if effective and key in OWNER_POWERS and not getattr(user, "totp_enabled", False):
        effective = False  # paused until they set up an authenticator
    return effective, label


def has_permission(db: Session, user: User, permission: str) -> bool:
    """Return the effective value of ``permission`` for ``user`` (1F.10)."""

    # Never-grantable capabilities are not permissions anyone can hold.
    if permission in NEVER_GRANTABLE or not is_valid_permission(permission):
        return False

    # F-4: resolve via effective_role, not the raw role column, so a flag-only
    # admin gets the same catalogue access require_admin_user's role-tier gate
    # already grants them.
    role = effective_role(user)
    if role in OWNER_ROLES:
        return True
    if role not in ADJUSTABLE:
        return False  # a regular user never holds a catalogue permission
    override = (
        db.query(PermissionOverride)
        .filter(
            PermissionOverride.user_id == user.id,
            PermissionOverride.permission == permission,
        )
        .first()
    )
    blocked = sub_admin_blocked(db) if role == UserRole.SECONDARY else set()
    return _decide(user, role, permission, override.state if override else None, blocked)[0]


def resolve_effective(db: Session, user: User) -> list[dict]:
    """The person's full effective permission set with state (1F.9.2)."""

    role = effective_role(user)
    overrides = _overrides_for(db, user.id) if role in ADJUSTABLE else {}
    blocked = sub_admin_blocked(db) if role == UserRole.SECONDARY else set()
    out: list[dict] = []
    for key in ALL_PERMISSIONS:
        effective, label = _decide(user, role, key, overrides.get(key), blocked)
        out.append(
            {
                "key": key,
                "effective": effective,
                "state": label,
                "role_default": role_default(key, role),
            }
        )
    return out


def modified_count(db: Session, user: User) -> int:
    return (
        db.query(PermissionOverride)
        .filter(PermissionOverride.user_id == user.id)
        .count()
    )


def _assert_adjustable(target: User) -> None:
    if effective_role(target) not in ADJUSTABLE:
        raise ApiError(
            ErrorCode.FORBIDDEN,
            "Only an Admin's or a sub-admin's permissions can be adjusted. Make the person a sub-admin first.",
            details={"reason": "not_a_sub_admin"},
        )


def _is_owner(user: User) -> bool:
    return effective_role(user) in OWNER_ROLES


def admin_ids(db: Session) -> set[int]:
    """The people holding the Admin tier."""

    rows = db.query(User.id).filter(User.role == UserRole.CO_ADMIN).all()
    return {row[0] for row in rows}


def is_admin(db: Session, user: User) -> bool:
    return effective_role(user) == UserRole.CO_ADMIN


def _refuse(message: str, reason: str, **details) -> ApiError:
    return ApiError(ErrorCode.FORBIDDEN, message, details={"reason": reason, **details})


def assert_may_act_on(actor: User, target: User, what: str = "do that to", *, allow_self: bool = False) -> None:
    """The chain of command: an Admin has power over sub-admins and users, a
    sub-admin over users only, and nobody over the owner. Power over a person
    needs a strictly higher tier."""

    if allow_self and actor.id == target.id:
        return
    if rank(target) >= 3 or rank(actor) <= rank(target):
        raise _refuse(f"You can't {what} someone of your own tier or above.", "above_your_tier")


def authorize_change(db: Session, actor: User, target: User, grants: list[str]) -> None:
    """Who may change ``target``'s permissions, and grant ``grants``.

    * The owner: anyone but themselves (their own powers are fixed).
    * An Admin with ``manage_roles``: sub-admins only -- never themselves,
      never another Admin -- and only everyday powers they hold themselves
      that the owner's ceiling lets a sub-admin hold.
    """

    if _is_owner(actor):
        return
    if target.id == actor.id:
        raise _refuse("You can't change your own permissions.", "self_change")
    if rank(target) >= rank(actor):
        raise _refuse(
            "You can only change a sub-admin's permissions. Only the site owner changes an Admin's.",
            "admin_protected" if rank(target) == rank(actor) else "owner_only",
        )
    blocked = sub_admin_blocked(db)
    for key in grants:
        if key in OWNER_POWERS:
            raise _refuse("Only the site owner can give site-owner powers.", "owner_only", permission=key)
        if key in blocked:
            raise _refuse(
                f"The site owner doesn't allow sub-admins to hold '{key}'.", "owner_ceiling", permission=key
            )
        if not has_permission(db, actor, key):
            raise _refuse(f"You can't give '{key}': you don't hold it yourself.", "not_yours_to_give", permission=key)


def set_override(
    db: Session, target: User, permission: str, state: str, actor_id: int | None, *, by_owner: bool = False
) -> None:
    """Set or clear a single override (1F.6.2).

    ``state`` is 'granted', 'revoked', or 'inherited' (clears the override).
    Never-grantable permissions (1F.8) are refused, and only an Admin's or a
    sub-admin's permissions are adjustable (users hold none, the owner holds
    all). An Admin's toggles change only through the owner (``by_owner``, the
    caller having checked the owner's authenticator code for a grant of a
    site-owner power). A sub-admin can never hold a site-owner power or one
    the owner's ceiling blocks.
    """

    _assert_adjustable(target)
    role = effective_role(target)

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
    if role == UserRole.CO_ADMIN:
        if not by_owner:
            raise _refuse("Only the site owner can change an Admin's powers.", "owner_only", permission=permission)
        if state == "granted" and permission in OWNER_POWERS and not getattr(target, "totp_enabled", False):
            raise _refuse(
                "This Admin must set up an authenticator app (Admin -> Security) before holding site-owner powers.",
                "authenticator_required",
            )
        # Keep only real deviations from the Admin default.
        if (state == "granted") == role_default(permission, role) and state != "inherited":
            state = "inherited"
    else:
        if permission in OWNER_POWERS:
            if not by_owner:
                raise _refuse(
                    "Only the site owner can give or take site-owner powers.", "owner_only", permission=permission
                )
            if state == "granted":
                raise _refuse(
                    "Site-owner powers belong to Admins. Make the person an Admin first.",
                    "admin_only",
                    permission=permission,
                )
            state = "inherited"  # nothing to store: a sub-admin never holds one
        elif state == "granted" and permission in sub_admin_blocked(db):
            raise _refuse(
                f"The site owner doesn't allow sub-admins to hold '{permission}'.",
                "owner_ceiling",
                permission=permission,
            )

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
    """Take every site-owner override from ``target`` (leaving the Admin tier)."""

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
    # A preset shapes everyday powers; site-owner powers are left as they are,
    # and a power the owner's ceiling blocks is skipped, not granted.
    reset_to_default(db, target, keep_owner_powers=True)
    blocked = sub_admin_blocked(db)
    by_owner = True  # the route already authorised the actor (authorize_change)
    for key in preset.get("revoke", []):
        if _presettable(key):
            set_override(db, target, key, "revoked", actor_id, by_owner=by_owner)
    for key in preset.get("grant", []):
        if _presettable(key) and key not in blocked:
            set_override(db, target, key, "granted", actor_id, by_owner=by_owner)


def preset_grants(db: Session, preset_key: str) -> list[str]:
    """The keys applying ``preset_key`` would grant, minus what the owner's
    ceiling blocks (those are skipped, so they never count as a grant)."""

    preset = _resolve_preset(db, preset_key) or {}
    blocked = sub_admin_blocked(db)
    return [k for k in preset.get("grant", []) if _presettable(k) and k not in blocked]


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


def list_managed_people(
    db: Session, *, modified_only: bool = False, include_admins: bool = False
) -> list[dict]:
    """Sub-admins (and, for the owner, Admins) with their modified count.

    Powers the Role & Permission Management list and its "Modified only" filter
    (SRS 1F.9.1).
    """

    roles = [UserRole.SECONDARY] + ([UserRole.CO_ADMIN] if include_admins else [])
    rows = (
        db.query(User)
        .filter(User.role.in_(roles))
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
                "admin": user.role == UserRole.CO_ADMIN,
                "appointed_by": user.appointed_by,
                "authenticator": bool(getattr(user, "totp_enabled", False)),
            }
        )
    return out
