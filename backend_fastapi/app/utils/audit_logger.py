import datetime
from sqlalchemy.orm import Session
from fastapi import Request
from ..models import AdminAuditLog, User
from .client_ip import resolve_client_ip


def log_admin_action(
    db: Session,
    request: Request,
    admin_user: User,
    action: str,
    target_type: str,
    target_id: str,
    result: str,
    previous_value: str = None,
    new_value: str = None,
):
    """
    Append-only admin audit log.
    action: enum string (PROMOTE, DEMOTE, DELETE_USER, BULK_DELETE, ROLE_CHANGE, SYSTEM_SETTING_CHANGE)
    result: 'success' or failure reason
    """
    # Uses the shared trusted-proxy-aware resolver (utils/client_ip) rather
    # than trusting a client-controlled X-Forwarded-For value directly --
    # that used to let the acting admin forge the source_ip recorded here.
    client_ip = resolve_client_ip(request)
    if client_ip == "unknown":
        client_ip = None
    from ..services import site_functions

    if client_ip is not None and not site_functions.record_ips(db):
        client_ip = None  # the owner switched address recording off

    admin_role = (
        admin_user.role.value
        if hasattr(admin_user.role, "value")
        else str(admin_user.role)
    )
    if getattr(admin_user, "permanent", False):
        admin_role = "permanent_admin"
    elif getattr(admin_user, "is_main_admin", False):
        admin_role = "admin"

    metadata = {
        "admin_role": admin_role,
        "target_type": target_type,
        "target_id": target_id,
        "result": result,
    }
    if previous_value is not None:
        metadata["previous_value"] = previous_value
    if new_value is not None:
        metadata["new_value"] = new_value

    log_entry = AdminAuditLog(
        user_id=admin_user.id,
        operator=(
            admin_user.email_plaintext
            if hasattr(admin_user, "email_plaintext")
            else None
        ),
        action=action,
        metadata_json=metadata,
        source_ip=client_ip,
        timestamp=datetime.datetime.utcnow(),
    )
    db.add(log_entry)
    db.commit()
