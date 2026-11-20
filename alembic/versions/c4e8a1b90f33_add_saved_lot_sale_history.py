"""add sale history columns to saved_lots

Revision ID: c4e8a1b90f33
Revises: b7c1e4a90d22
Create Date: 2026-11-19 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e8a1b90f33"
down_revision: Union[str, Sequence[str], None] = "b7c1e4a90d22"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("saved_lots", sa.Column("sale_history", sa.JSON(), nullable=True))
    op.add_column("saved_lots", sa.Column("sale_status", sa.String(), nullable=True))
    op.add_column("saved_lots", sa.Column("sale_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("saved_lots", sa.Column("purchase_price", sa.Integer(), nullable=True))
    op.add_column(
        "saved_lots",
        sa.Column("sale_history_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("saved_lots", "sale_history_fetched_at")
    op.drop_column("saved_lots", "purchase_price")
    op.drop_column("saved_lots", "sale_date")
    op.drop_column("saved_lots", "sale_status")
    op.drop_column("saved_lots", "sale_history")
