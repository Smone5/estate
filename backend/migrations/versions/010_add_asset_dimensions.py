"""Add optional asset dimensions for logistics planning.

Revision ID: 010
Revises: 9a2c0fe8d21c
Create Date: 2026-06-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010"
down_revision: Union[str, Sequence[str], None] = "9a2c0fe8d21c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("length_in", sa.Float(), nullable=True))
    op.add_column("assets", sa.Column("width_in", sa.Float(), nullable=True))
    op.add_column("assets", sa.Column("height_in", sa.Float(), nullable=True))
    op.add_column("assets", sa.Column("weight_lb", sa.Float(), nullable=True))
    op.add_column("assets", sa.Column("dimension_source", sa.String(length=30), nullable=True))
    op.add_column("assets", sa.Column("dimension_confidence", sa.String(length=20), nullable=True))
    op.add_column("assets", sa.Column("dimension_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("assets", "dimension_notes")
    op.drop_column("assets", "dimension_confidence")
    op.drop_column("assets", "dimension_source")
    op.drop_column("assets", "weight_lb")
    op.drop_column("assets", "height_in")
    op.drop_column("assets", "width_in")
    op.drop_column("assets", "length_in")
