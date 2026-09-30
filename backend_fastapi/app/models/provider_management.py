"""Multi-provider admin management (SRS Part 2: 2D).

Extends the single-provider-per-service model Part 1 built
(``ProviderCredentials``, still used by the existing PA-only
``/admin/system-providers`` single-slot endpoints) with the richer object
2D.2 specifies: many providers per service, integer priority with equal
load distribution across providers sharing a level (2D.3), a status
lifecycle, live verification before activation (2D.5), and usage/error
statistics. Credentials stay Main-Admin-only per the resolved D7 decision
(SRS 1H.11) -- the same boundary already enforced and tested for the
single-provider system (see test_system_providers.py).
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    func,
)

from .base import Base

# ocr | translation | ai -- the three provider types 2D.2 names.
PROVIDER_SERVICES = ("ocr", "translation", "ai")

# 2D.2 status lifecycle. A provider starts "inactive" until it passes the
# live test (2D.5); "failing" is automatic (health-check driven) and
# removed from rotation until it recovers; "disabled" is a deliberate admin
# action.
STATUS_ACTIVE = "active"
STATUS_INACTIVE = "inactive"
STATUS_FAILING = "failing"
STATUS_DISABLED = "disabled"
PROVIDER_STATUSES = (STATUS_ACTIVE, STATUS_INACTIVE, STATUS_FAILING, STATUS_DISABLED)

DEFAULT_PRIORITY = 1


class SystemProviderInstance(Base):
    """One administrator-configured provider (2D.2's provider record)."""

    __tablename__ = "system_provider_instances"

    id = Column(Integer, primary_key=True)
    # Display name (2D.2 "provider_name") -- purely descriptive, admin-chosen.
    provider_name = Column(String(120), nullable=False)
    # Which service this instance serves: ocr | translation | ai.
    service = Column(String(16), nullable=False)
    # Which known provider template this is (e.g. google_cloud_vision,
    # custom); drives PROVIDER_DEFAULTS lookups in provider_config.py.
    provider_id = Column(String(64), nullable=False)

    api_url = Column(String(500), nullable=True)
    # Write-only, encrypted at rest, never displayed/logged (1H.3).
    api_key = Column(String(255), nullable=True)
    website_url = Column(String(500), nullable=True)
    config = Column(JSON, nullable=True)  # headers/model/etc.

    status = Column(
        String(16),
        nullable=False,
        default=STATUS_INACTIVE,
        server_default=STATUS_INACTIVE,
    )
    priority = Column(
        Integer,
        nullable=False,
        default=DEFAULT_PRIORITY,
        server_default=str(DEFAULT_PRIORITY),
    )

    # {"requests": int, "volume": int, "cost": float|None}
    usage_stats = Column(JSON, nullable=True, default=dict)
    # {"failure_count": int, "consecutive_failures": int, "failure_rate": float,
    #  "last_error": str|None, "last_error_at": iso str|None}
    error_stats = Column(JSON, nullable=True, default=dict)

    last_verified_at = Column(DateTime, nullable=True)
    last_health_check_at = Column(DateTime, nullable=True)

    # Round-robin cursor for "equal distribution" among providers sharing a
    # priority level (2D.3) -- persisted so distribution survives restarts
    # and is independently observable per provider.
    rotation_counter = Column(Integer, nullable=False, default=0, server_default="0")

    created_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


__all__ = [
    "SystemProviderInstance",
    "PROVIDER_SERVICES",
    "PROVIDER_STATUSES",
    "STATUS_ACTIVE",
    "STATUS_INACTIVE",
    "STATUS_FAILING",
    "STATUS_DISABLED",
    "DEFAULT_PRIORITY",
]
