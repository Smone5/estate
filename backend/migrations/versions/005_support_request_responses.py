"""Support request responses and audit metadata.

Revision ID: 005
Revises: 004
Create Date: 2026-06-13 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "005"
down_revision: Union[str, Sequence[str], None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "support_requests",
        sa.Column("responded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("support_requests", sa.Column("admin_response", sa.Text(), nullable=True))
    op.add_column(
        "support_requests",
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "support_requests",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_support_requests_responded_by_id_users",
        "support_requests",
        "users",
        ["responded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "idx_support_requests_responded_by_id",
        "support_requests",
        ["responded_by_id"],
    )
    op.drop_constraint("ck_support_requests_status", "support_requests", type_="check")
    op.create_check_constraint(
        "ck_support_requests_status",
        "support_requests",
        "status IN ('OPEN', 'RESPONDED', 'RESOLVED')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_support_requests_status", "support_requests", type_="check")
    op.create_check_constraint(
        "ck_support_requests_status",
        "support_requests",
        "status IN ('OPEN', 'RESOLVED')",
    )
    op.drop_index("idx_support_requests_responded_by_id", table_name="support_requests")
    op.drop_constraint(
        "fk_support_requests_responded_by_id_users",
        "support_requests",
        type_="foreignkey",
    )
    op.drop_column("support_requests", "resolved_at")
    op.drop_column("support_requests", "responded_at")
    op.drop_column("support_requests", "admin_response")
    op.drop_column("support_requests", "responded_by_id")
