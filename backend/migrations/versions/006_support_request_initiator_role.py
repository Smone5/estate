"""Track support request initiator role.

Revision ID: 006
Revises: 005
Create Date: 2026-06-16 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "006"
down_revision: Union[str, Sequence[str], None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "support_requests",
        sa.Column(
            "initiator_role",
            sa.String(length=10),
            server_default="HEIR",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_support_requests_initiator_role",
        "support_requests",
        "initiator_role IN ('HEIR', 'ADMIN')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_support_requests_initiator_role",
        "support_requests",
        type_="check",
    )
    op.drop_column("support_requests", "initiator_role")
