"""Cultivation ranking system (SRS 3D).

Thirteen realms, each with 10 sub-stages, progressing on reputation (3C).
Realm names/thresholds/color-band/dedicated-contributor cutoff are
administrator configurable rows in ``cultivation_realms`` -- nothing here is
hardcoded business logic that would need a code change to retheme (3F).

Note on 3D.5: whether a realm counts as "dedicated contributor" is
informational only. There is no automated queue-priority behavior attached
to it -- when a high-rank reader asks directly for something, a moderator or
administrator decides by hand, using the requester's visible rank as
context.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models.community import CultivationRealmConfig

# Seed data only (3D.2/3D.3) -- loaded once via ``ensure_seeded``; every value
# is a starting default an administrator can freely edit afterward. Doubles
# from Foundation Establishment onward, per the SRS's example progression;
# D16 (thresholds beyond Soul Formation) stays open but administrator
# configurable regardless.
_DEFAULT_REALMS: List[Dict[str, Any]] = [
    {
        "name": "Qi Refining",
        "reputation_threshold": 0,
        "color_band": "gray",
        "dedicated_contributor": False,
    },
    {
        "name": "Foundation Establishment",
        "reputation_threshold": 5_000,
        "color_band": "gold_light",
        "dedicated_contributor": False,
    },
    {
        "name": "Core Formation",
        "reputation_threshold": 15_000,
        "color_band": "gold",
        "dedicated_contributor": False,
    },
    {
        "name": "Nascent Soul",
        "reputation_threshold": 30_000,
        "color_band": "sparkling_gold",
        "dedicated_contributor": True,
    },
    {
        "name": "Soul Formation",
        "reputation_threshold": 60_000,
        "color_band": "sparkling_gold",
        "dedicated_contributor": True,
    },
    {
        "name": "Void Refinement",
        "reputation_threshold": 120_000,
        "color_band": "sparkling_gold",
        "dedicated_contributor": True,
    },
    {
        "name": "Integration",
        "reputation_threshold": 240_000,
        "color_band": "sparkling_gold",
        "dedicated_contributor": True,
    },
    {
        "name": "Mahayana",
        "reputation_threshold": 480_000,
        "color_band": "diamond",
        "dedicated_contributor": True,
    },
    {
        "name": "Ascendant",
        "reputation_threshold": 960_000,
        "color_band": "diamond",
        "dedicated_contributor": True,
    },
    {
        "name": "Immortal",
        "reputation_threshold": 1_920_000,
        "color_band": "purple",
        "dedicated_contributor": True,
    },
    {
        "name": "Immortal King",
        "reputation_threshold": 3_840_000,
        "color_band": "purple",
        "dedicated_contributor": True,
    },
    {
        "name": "Immortal Emperor",
        "reputation_threshold": 7_680_000,
        "color_band": "purple",
        "dedicated_contributor": True,
    },
    {
        "name": "Immortal Sovereign",
        "reputation_threshold": 15_360_000,
        "color_band": "purple",
        "dedicated_contributor": True,
    },
]


def ensure_seeded(db: Session) -> None:
    """Insert the default realm ladder if the table is empty. Idempotent."""

    if db.query(CultivationRealmConfig).first() is not None:
        return
    for index, realm in enumerate(_DEFAULT_REALMS):
        db.add(
            CultivationRealmConfig(
                order_index=index,
                name=realm["name"],
                stage_count=10,
                reputation_threshold=realm["reputation_threshold"],
                color_band=realm["color_band"],
                dedicated_contributor=realm["dedicated_contributor"],
            )
        )
    db.commit()


def list_realms(db: Session) -> List[CultivationRealmConfig]:
    ensure_seeded(db)
    return (
        db.query(CultivationRealmConfig)
        .order_by(CultivationRealmConfig.order_index)
        .all()
    )


def realm_to_dict(realm: CultivationRealmConfig) -> Dict[str, Any]:
    return {
        "id": realm.id,
        "order_index": realm.order_index,
        "name": realm.name,
        "stage_count": realm.stage_count,
        "reputation_threshold": realm.reputation_threshold,
        "color_band": realm.color_band,
        "dedicated_contributor": bool(realm.dedicated_contributor),
    }


def rank_for(db: Session, reputation: int) -> Dict[str, Any]:
    """Return the realm/stage badge for a given reputation total (3D.4)."""

    realms = list_realms(db)
    reputation = max(0, int(reputation or 0))

    current: Optional[CultivationRealmConfig] = None
    next_realm: Optional[CultivationRealmConfig] = None
    for i, realm in enumerate(realms):
        if realm.reputation_threshold <= reputation:
            current = realm
            next_realm = realms[i + 1] if i + 1 < len(realms) else None
        else:
            break

    if current is None:
        # Table not seeded / no realm starts at 0 -- degrade gracefully.
        return {
            "realm_name": None,
            "realm_index": None,
            "stage": 1,
            "color_band": "gray",
            "reputation": reputation,
            "dedicated_contributor": False,
            "next_realm_name": realms[0].name if realms else None,
            "next_realm_threshold": realms[0].reputation_threshold if realms else None,
        }

    stage_count = current.stage_count or 10
    if next_realm is not None:
        span = max(1, next_realm.reputation_threshold - current.reputation_threshold)
        progress = reputation - current.reputation_threshold
        stage = 1 + min(stage_count - 1, (progress * stage_count) // span)
    else:
        # Final configured realm: stage climbs by the same span as the
        # second-to-last realm, then holds at the max stage.
        prior = realms[current.order_index - 1] if current.order_index > 0 else None
        span = max(
            1,
            current.reputation_threshold - (prior.reputation_threshold if prior else 0),
        )
        progress = reputation - current.reputation_threshold
        stage = 1 + min(stage_count - 1, (progress * stage_count) // span)

    return {
        "realm_name": current.name,
        "realm_index": current.order_index,
        "stage": int(stage),
        "color_band": current.color_band,
        "reputation": reputation,
        "dedicated_contributor": bool(current.dedicated_contributor),
        "next_realm_name": next_realm.name if next_realm else None,
        "next_realm_threshold": next_realm.reputation_threshold if next_realm else None,
    }


def update_realm(
    db: Session,
    realm_id: int,
    *,
    name: Optional[str] = None,
    reputation_threshold: Optional[int] = None,
    stage_count: Optional[int] = None,
    color_band: Optional[str] = None,
    dedicated_contributor: Optional[bool] = None,
) -> Optional[CultivationRealmConfig]:
    """Administrator edit of one realm's name/threshold/styling (3D.2).

    Never touches a specific user's rank directly -- ``alter_rank`` stays in
    NEVER_GRANTABLE (1E.5.3); this only reshapes the ladder everyone's
    reputation is measured against.
    """

    realm = db.get(CultivationRealmConfig, realm_id)
    if realm is None:
        return None
    if name is not None:
        realm.name = name
    if reputation_threshold is not None:
        realm.reputation_threshold = reputation_threshold
    if stage_count is not None:
        realm.stage_count = stage_count
    if color_band is not None:
        realm.color_band = color_band
    if dedicated_contributor is not None:
        realm.dedicated_contributor = dedicated_contributor
    db.commit()
    db.refresh(realm)
    return realm


__all__ = [
    "ensure_seeded",
    "list_realms",
    "realm_to_dict",
    "rank_for",
    "update_realm",
]
