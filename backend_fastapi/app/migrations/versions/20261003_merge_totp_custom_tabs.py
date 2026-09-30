"""Join the two heads that both follow 20261001_page_mirroring.

``20261002_admin_totp`` (admin second factor) and ``20261002_drop_custom_tabs``
were written in parallel and merged one after the other, leaving two heads, so
``alembic upgrade head`` refused to run. They touch different tables, so this
revision only joins them; it changes nothing itself.

Revision ID: 20261003_merge_totp_custom_tabs
Revises: 20261002_admin_totp, 20261002_drop_custom_tabs
"""

from __future__ import annotations

revision = "20261003_merge_totp_custom_tabs"
down_revision = ("20261002_admin_totp", "20261002_drop_custom_tabs")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
