"""add users

Moves the admin account from <config_dir>/.admin.env (written by the old
/auth/setup) into the database.

Revision ID: b4e1f0c2d9a3
Revises: a7c3e91d2b10
Create Date: 2026-11-24 12:00:00

"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b4e1f0c2d9a3'
down_revision: Union[str, None] = 'a7c3e91d2b10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _legacy_admin() -> tuple[str, str] | None:
    from app.settings import Settings

    path = Settings().config_dir / ".admin.env"
    if not path.exists():
        return None
    env = dict(
        line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line
    )
    pw_hash = env.get("HAULARR_ADMIN_PASSWORD_HASH", "").strip()
    return (env.get("HAULARR_ADMIN_USERNAME", "admin").strip(), pw_hash) if pw_hash else None


def upgrade() -> None:
    users = op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    admin = _legacy_admin()
    if admin:
        op.bulk_insert(users, [{
            "id": str(uuid.uuid4()), "username": admin[0], "password_hash": admin[1],
            "is_admin": True, "created_at": datetime.now(timezone.utc),
        }])


def downgrade() -> None:
    op.drop_table("users")
