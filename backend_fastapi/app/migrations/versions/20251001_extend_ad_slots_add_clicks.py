"""Extend ad_slots table and add ad_clicks"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20251001_extend_ad_slots_add_clicks"
down_revision = "20250930_create_ad_slots_table"
branch_labels = None
depends_on = None


def _table_has_column(inspector, table_name, column_name):
    if not inspector.has_table(table_name):
        return False

    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("ad_slots"):
        return

    columns = {col["name"]: col for col in inspector.get_columns("ad_slots")}

    if "html_code" not in columns:
        op.add_column("ad_slots", sa.Column("html_code", sa.Text(), nullable=True))
        columns["html_code"] = {"nullable": True}
    else:
        columns["html_code"] = {**columns["html_code"]}

    new_columns = {
        "slot_key": sa.Column("slot_key", sa.String(length=100), nullable=True),
        "type": sa.Column(
            "type", sa.String(length=20), nullable=False, server_default="image"
        ),
        "image_url": sa.Column("image_url", sa.String(length=500), nullable=True),
        "link_url": sa.Column("link_url", sa.String(length=500), nullable=True),
        "alt_text": sa.Column("alt_text", sa.String(length=255), nullable=True),
        "metadata": sa.Column("metadata", sa.JSON(), nullable=True),
        "enabled": sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        "provider_id": sa.Column("provider_id", sa.Integer(), nullable=True),
        "created_at": sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        "updated_at": sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    }

    with op.batch_alter_table("ad_slots", schema=None) as batch_op:
        html_code_info = columns.get("html_code")
        if html_code_info and not html_code_info.get("nullable", True):
            batch_op.alter_column("html_code", existing_type=sa.Text(), nullable=True)

        for name, column in new_columns.items():
            if name not in columns:
                batch_op.add_column(column)
                columns[name] = {"nullable": column.nullable}

    inspector = inspect(bind)
    columns = {col["name"]: col for col in inspector.get_columns("ad_slots")}

    if "slot_key" in columns:
        op.execute("UPDATE ad_slots SET slot_key = COALESCE(slot_key, name)")

        with op.batch_alter_table("ad_slots", schema=None) as batch_op:
            if columns["slot_key"].get("nullable", True):
                batch_op.alter_column(
                    "slot_key", existing_type=sa.String(length=100), nullable=False
                )

            unique_constraints = {
                uc["name"] for uc in inspector.get_unique_constraints("ad_slots")
            }
            if "uq_ad_slots_slot_key" not in unique_constraints:
                batch_op.create_unique_constraint("uq_ad_slots_slot_key", ["slot_key"])

            foreign_keys = {
                fk["name"]
                for fk in inspector.get_foreign_keys("ad_slots")
                if fk.get("name")
            }
            if (
                "fk_ad_slots_provider_id_global_ad_providers" not in foreign_keys
                and _table_has_column(inspector, "ad_slots", "provider_id")
            ):
                batch_op.create_foreign_key(
                    "fk_ad_slots_provider_id_global_ad_providers",
                    "global_ad_providers",
                    ["provider_id"],
                    ["id"],
                )

    inspector = inspect(bind)
    if not inspector.has_table("ad_clicks"):
        op.create_table(
            "ad_clicks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("slot_id", sa.Integer(), nullable=False),
            sa.Column("user_email", sa.String(length=255), nullable=True),
            sa.Column("ip_address", sa.String(length=45), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["slot_id"], ["ad_slots.id"], ondelete="CASCADE"),
        )

    inspector = inspect(bind)
    if inspector.has_table("ad_clicks"):
        existing_indexes = {
            index["name"] for index in inspector.get_indexes("ad_clicks")
        }
        if "ix_ad_clicks_slot_id" not in existing_indexes:
            op.create_index("ix_ad_clicks_slot_id", "ad_clicks", ["slot_id"])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("ad_clicks"):
        existing_indexes = {
            index["name"] for index in inspector.get_indexes("ad_clicks")
        }
        if "ix_ad_clicks_slot_id" in existing_indexes:
            op.drop_index("ix_ad_clicks_slot_id", table_name="ad_clicks")
        op.drop_table("ad_clicks")

    inspector = inspect(bind)
    if not inspector.has_table("ad_slots"):
        return

    columns = {col["name"]: col for col in inspector.get_columns("ad_slots")}

    with op.batch_alter_table("ad_slots", schema=None) as batch_op:
        foreign_keys = {
            fk["name"]
            for fk in inspector.get_foreign_keys("ad_slots")
            if fk.get("name")
        }
        if "fk_ad_slots_provider_id_global_ad_providers" in foreign_keys:
            batch_op.drop_constraint(
                "fk_ad_slots_provider_id_global_ad_providers", type_="foreignkey"
            )

        unique_constraints = {
            uc["name"] for uc in inspector.get_unique_constraints("ad_slots")
        }
        if "uq_ad_slots_slot_key" in unique_constraints:
            batch_op.drop_constraint("uq_ad_slots_slot_key", type_="unique")

        for column_name in [
            "updated_at",
            "created_at",
            "provider_id",
            "enabled",
            "metadata",
            "alt_text",
            "link_url",
            "image_url",
            "type",
            "slot_key",
        ]:
            if column_name in columns:
                batch_op.drop_column(column_name)

        if "html_code" in columns and columns["html_code"].get("nullable", True):
            batch_op.alter_column("html_code", existing_type=sa.Text(), nullable=False)
