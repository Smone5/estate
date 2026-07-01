"""Add session practice-phase configuration and heir completion tracking.

Revision ID: 011
Revises: 010
Create Date: 2026-07-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011"
down_revision: Union[str, Sequence[str], None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing sessions remain optional to avoid blocking an in-flight estate.
    # Newly created sessions explicitly set practice_required=True in the API.
    op.add_column(
        "sessions",
        sa.Column("practice_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "sessions",
        sa.Column("simulation_published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("practice_completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "practice_completed_at")
    op.drop_column("sessions", "simulation_published_at")
    op.drop_column("sessions", "practice_required")
