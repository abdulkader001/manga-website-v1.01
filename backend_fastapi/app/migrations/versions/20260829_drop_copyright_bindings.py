"""Drop copyright_bindings, fully dead schema (F-27)

grep -rln "CopyrightBinding" across backend_fastapi/app/api, services, and
tasks returned zero matches before this change -- no router, service, or
task referenced this model anywhere except its own definition, its one
relationship on User, and migration history. Removing rather than building
out whatever rights-attestation flow it was meant to support (its column
names -- phrase_hash, enforced-unique by 20251005_enforce_unique_phrase_hash
-- suggest a removed or never-finished feature).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260829_drop_copyright_bindings"
down_revision = "20260828_comments_parent_fk_set_null"
branch_labels = None
depends_on = None

TABLE = "copyright_bindings"


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
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("manga_title", sa.String(length=255), nullable=True),
        sa.Column("proof_url", sa.String(length=500), nullable=True),
        sa.Column("phrase_hash", sa.String(length=64), unique=True, nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
