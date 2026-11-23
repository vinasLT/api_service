"""add sale_count to saved_lots

Revision ID: d5e7c2a84b19
Revises: c4e8a1b90f33
Create Date: 2026-11-22 11:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e7c2a84b19"
down_revision: Union[str, Sequence[str], None] = "c4e8a1b90f33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("saved_lots", sa.Column("sale_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("saved_lots", "sale_count")
