"""Fix CustomPageVisibility enum values
Revision ID: 0c924aa01af3
Revises: d9d80c5ffdd8
Create Date: 2026-04-12 01:09:52.961301
"""

from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0c924aa01af3"
down_revision: Union[str, None] = "4be0d9f7edb6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Rename the existing enum type to something else
        op.execute(
            "ALTER TYPE custom_page_visibility RENAME TO custom_page_visibility_old"
        )

        # Create the new enum type with lower-case values
        op.execute(
            "CREATE TYPE custom_page_visibility AS ENUM ('public', 'authenticated', 'secondary_admin', 'admin', 'permanent_admin')"
        )

        # Alter the column to use the new enum type, casting existing values to lower-case
        op.execute("ALTER TABLE custom_pages ALTER COLUMN visibility DROP DEFAULT")
        op.execute(
            "ALTER TABLE custom_pages ALTER COLUMN visibility TYPE custom_page_visibility USING LOWER(visibility::text)::custom_page_visibility"
        )
        op.execute(
            "ALTER TABLE custom_pages ALTER COLUMN visibility SET DEFAULT 'public'"
        )

        # Drop the old enum type
        op.execute("DROP TYPE custom_page_visibility_old")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Rename the existing enum type back to something else
        op.execute(
            "ALTER TYPE custom_page_visibility RENAME TO custom_page_visibility_new"
        )

        # Recreate the upper-case enum type (if that was the previous state)
        op.execute(
            "CREATE TYPE custom_page_visibility AS ENUM ('PUBLIC', 'AUTHENTICATED', 'SECONDARY_ADMIN', 'ADMIN', 'PERMANENT_ADMIN')"
        )

        # Alter the column to use the old enum type, casting existing values to upper-case
        op.execute("ALTER TABLE custom_pages ALTER COLUMN visibility DROP DEFAULT")
        op.execute(
            "ALTER TABLE custom_pages ALTER COLUMN visibility TYPE custom_page_visibility USING UPPER(visibility::text)::custom_page_visibility"
        )
        op.execute(
            "ALTER TABLE custom_pages ALTER COLUMN visibility SET DEFAULT 'PUBLIC'"
        )

        # Drop the new enum type
        op.execute("DROP TYPE custom_page_visibility_new")
