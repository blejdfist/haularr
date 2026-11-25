"""add source last_scan_error

Revision ID: a7c3e91d2b10
Revises: 52f507048e57
Create Date: 2026-11-23 12:00:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a7c3e91d2b10"
down_revision: Union[str, None] = "52f507048e57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("source_instances") as batch_op:
        batch_op.add_column(sa.Column("last_scan_error", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("source_instances") as batch_op:
        batch_op.drop_column("last_scan_error")
