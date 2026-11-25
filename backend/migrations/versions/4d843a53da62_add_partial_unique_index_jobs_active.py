"""add_partial_unique_index_jobs_active

Revision ID: 4d843a53da62
Revises: ad142e3fcdc1
Create Date: 2026-11-13 08:57:52.582586

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "4d843a53da62"
down_revision: Union[str, None] = "ad142e3fcdc1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Partial unique index: at most one non-terminal job per source item
    # (ended_at IS NULL means the job is active/non-terminal)
    op.create_index(
        "ix_jobs_one_active_per_item",
        "jobs",
        ["source_item_id"],
        unique=True,
        sqlite_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_one_active_per_item", table_name="jobs")
