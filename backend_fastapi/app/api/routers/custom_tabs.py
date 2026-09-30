"""Routes for managing custom navigation tabs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ...core.db import get_db
from ...dependencies.auth import get_current_user, is_main_admin
from ...models import CustomTab, User
from ...schemas.custom_tabs import CustomTabCreate
from ...utils.sanitizer import strip_all_html

router = APIRouter(prefix="/custom-tabs", tags=["custom_tabs"])


@router.get("")
def list_tabs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, object]]:
    """Return global and user-specific custom tabs."""

    tabs = (
        db.query(CustomTab)
        .filter(
            (CustomTab.is_global.is_(True)) | (CustomTab.user_id == current_user.id)
        )
        .order_by(CustomTab.order.asc(), CustomTab.id.asc())
        .all()
    )
    return [
        {
            "id": tab.id,
            "title": tab.title,
            "url": tab.url,
            "is_global": bool(tab.is_global),
            "order": tab.order,
        }
        for tab in tabs
    ]


@router.post("")
def add_tab(
    payload: CustomTabCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """Add a custom tab for the user or globally."""

    title = strip_all_html(payload.title).strip()

    if payload.is_global and not is_main_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can add global tabs",
        )

    tab = CustomTab(
        title=title,
        url=payload.url,
        is_global=payload.is_global,
        user_id=None if payload.is_global else current_user.id,
    )
    if payload.order is not None:
        tab.order = payload.order

    db.add(tab)
    db.commit()
    db.refresh(tab)

    return {
        "id": tab.id,
        "title": tab.title,
        "url": tab.url,
        "is_global": bool(tab.is_global),
        "order": tab.order,
    }


@router.delete("/{tab_id}")
def delete_tab(
    tab_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    """Delete a tab owned by the user or a global tab (admin only)."""

    tab = db.get(CustomTab, tab_id)
    if not tab:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tab not found"
        )

    if tab.is_global:
        if not is_main_admin(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can delete global tabs",
            )
    elif tab.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete another user's tab",
        )

    db.delete(tab)
    db.commit()

    return {"message": f"Tab {tab_id} deleted"}
