"""rename job stages for the seedbox download stage

download -> transfer, publish -> move; resolve_source folded into transfer;
confirm_import and notify removed (jobs there move on to cleanup). Jobs parked
for lack of a fetch config get their own status, waiting_transfer, since
waiting_source now means "still downloading on the seedbox".

Revision ID: c5d2a8e41f07
Revises: b4e1f0c2d9a3
Create Date: 2026-11-24 12:00:00

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "c5d2a8e41f07"
down_revision: Union[str, None] = "b4e1f0c2d9a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE jobs SET status = 'waiting_transfer'"
        " WHERE status = 'waiting_source' AND error_code = 'no_transfer_config'"
    )
    op.execute("UPDATE jobs SET stage = 'transfer' WHERE stage IN ('download', 'resolve_source')")
    op.execute("UPDATE jobs SET stage = 'move' WHERE stage = 'publish'")
    op.execute("UPDATE jobs SET stage = 'cleanup' WHERE stage IN ('confirm_import', 'notify')")
    op.execute(
        "DELETE FROM stage_runs WHERE stage IN ('resolve_source', 'confirm_import', 'notify')"
    )
    op.execute("UPDATE stage_runs SET stage = 'transfer' WHERE stage = 'download'")
    op.execute("UPDATE stage_runs SET stage = 'move' WHERE stage = 'publish'")


def downgrade() -> None:
    op.execute("UPDATE stage_runs SET stage = 'publish' WHERE stage = 'move'")
    op.execute("UPDATE stage_runs SET stage = 'download' WHERE stage = 'transfer'")
    op.execute("UPDATE jobs SET stage = 'publish' WHERE stage = 'move'")
    op.execute("UPDATE jobs SET stage = 'download' WHERE stage = 'transfer'")
    op.execute("UPDATE jobs SET status = 'waiting_source' WHERE status = 'waiting_transfer'")
