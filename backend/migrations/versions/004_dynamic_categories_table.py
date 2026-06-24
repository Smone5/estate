"""Dynamic categories table.

Revision ID: 004
Revises: 003
Create Date: 2026-06-11 20:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, Sequence[str], None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop check constraint from assets
    op.drop_constraint("ck_assets_category", "assets", type_="check")

    # 2. Alter assets.category column length
    op.alter_column(
        "assets",
        "category",
        existing_type=sa.String(length=20),
        type_=sa.String(length=100),
        existing_nullable=True,
    )

    # 3. Create categories table
    op.create_table(
        "categories",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.UniqueConstraint("session_id", "name", name="uq_categories_session_name"),
    )
    op.create_index("idx_categories_session_id", "categories", ["session_id"])


def downgrade() -> None:
    # 1. Drop categories table
    op.drop_index("idx_categories_session_id", table_name="categories")
    op.drop_table("categories")

    # 2. Revert assets.category column length
    op.alter_column(
        "assets",
        "category",
        existing_type=sa.String(length=100),
        type_=sa.String(length=20),
        existing_nullable=True,
    )

    # 3. Recreate check constraint
    op.create_check_constraint(
        "ck_assets_category",
        "assets",
        "category IN ('Jewelry', 'Furniture', 'Art', 'Other') OR category IS NULL",
    )
