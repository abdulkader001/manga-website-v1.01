"""Add is_system to provider_credentials
Revision ID: 1307b999f755
Revises: 20251223_add_enabled_column_to_provider_credentials
Create Date: 2025-10-18 08:16:41.271664
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "1307b999f755"
down_revision: Union[str, None] = "20251223_add_enabled_column_to_provider_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("provider_credentials") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_system", sa.Boolean(), nullable=False, server_default=sa.true()
            )
        )

    op.execute(
        "UPDATE provider_credentials SET is_system = TRUE WHERE is_system IS NULL"
    )

    with op.batch_alter_table("provider_credentials") as batch_op:
        batch_op.alter_column("is_system", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("provider_credentials") as batch_op:
        batch_op.drop_column("is_system")
