"""Drop social_links, fully dead schema (F-36)

``social_links`` was created by 20250909_update_bookmarks_readhistory_sociallinks
and later patched (icon column, created_at/updated_at) by later migrations, but
no ORM model was ever declared for it -- it has been dead from the
application's perspective since it was introduced. `social_links` as a string
does appear in backend_fastapi/app/api/routers/branding.py, but only as a
local variable name derived from the `socialLinks` JSON key stored inside the
`settings` table's `branding` row; that code never touches this table. A
repo-wide grep for the table name outside migrations turned up nothing else.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260830_drop_social_links"
down_revision = "20260829_drop_copyright_bindings"
branch_labels = None
depends_on = None

TABLE = "social_links"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        op.drop_table(TABLE)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(length=50), nullable=True),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("icon", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
