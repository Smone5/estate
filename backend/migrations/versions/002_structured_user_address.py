"""Add structured address fields to users.

Revision ID: 002
Revises: 001
Create Date: 2026-06-11 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "002"
down_revision: Union[str, Sequence[str], None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ADDRESS_COLUMNS = (
    ("address_line1", "VARCHAR(255)"),
    ("address_line2", "VARCHAR(255)"),
    ("address_city", "VARCHAR(100)"),
    ("address_region", "VARCHAR(100)"),
    ("address_postal_code", "VARCHAR(40)"),
    ("address_country", "VARCHAR(100)"),
)


def upgrade() -> None:
    for name, column_type in ADDRESS_COLUMNS:
        op.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {name} {column_type};")


def downgrade() -> None:
    for name, _column_type in reversed(ADDRESS_COLUMNS):
        op.execute(f"ALTER TABLE users DROP COLUMN IF EXISTS {name};")
