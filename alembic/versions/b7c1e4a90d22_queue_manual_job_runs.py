"""queue manual job runs

Revision ID: b7c1e4a90d22
Revises: 5dd6e4fab22d
Create Date: 2026-11-16 13:16:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c1e4a90d22"
down_revision: Union[str, Sequence[str], None] = "5dd6e4fab22d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_runs", sa.Column("requested_by", sa.String(length=255), nullable=True))
    op.create_index(
        "ux_job_runs_one_queued",
        "job_runs",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("status = 'queued'"),
        sqlite_where=sa.text("status = 'queued'"),
    )


def downgrade() -> None:
    op.drop_index("ux_job_runs_one_queued", table_name="job_runs")
    op.drop_column("job_runs", "requested_by")
