"""split_source_connection_config_credential

Revision ID: 52f507048e57
Revises: 4d843a53da62
Create Date: 2026-11-13 10:48:35.878773

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "52f507048e57"
down_revision: Union[str, None] = "4d843a53da62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite requires batch mode (render_as_batch=True in env.py) for column changes.
    with op.batch_alter_table("source_instances") as batch_op:
        # Add new columns
        batch_op.add_column(
            sa.Column("connection_config_json", sa.JSON(), nullable=False, server_default="{}")
        )
        batch_op.add_column(
            sa.Column("credential_ref", sa.Text(), nullable=False, server_default="")
        )

    # Migrate existing data: parse the old connection_secret_ref JSON blob.
    # Non-sensitive keys go into connection_config_json; password-like keys
    # stay in credential_ref as a JSON object (still plaintext — users who had
    # plaintext passwords before will need to re-save to get encryption).
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, connection_secret_ref FROM source_instances")
    ).fetchall()

    import json

    _SENSITIVE_KEYS = {"password", "api_key", "apikey", "secret", "token"}

    for row_id, raw in rows:
        try:
            data = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError):
            data = {}

        config = {k: v for k, v in data.items() if k.lower() not in _SENSITIVE_KEYS}
        creds = {k: v for k, v in data.items() if k.lower() in _SENSITIVE_KEYS}
        # Credential stored as JSON blob; will be encrypted on next save
        cred_ref = json.dumps(creds) if creds else ""

        conn.execute(
            sa.text(
                "UPDATE source_instances "
                "SET connection_config_json = :cfg, credential_ref = :cred "
                "WHERE id = :id"
            ),
            {"cfg": json.dumps(config), "cred": cred_ref, "id": row_id},
        )

    # Drop old column
    with op.batch_alter_table("source_instances") as batch_op:
        batch_op.drop_column("connection_secret_ref")


def downgrade() -> None:
    # Reverse: merge config + credential back into connection_secret_ref
    conn = op.get_bind()

    with op.batch_alter_table("source_instances") as batch_op:
        batch_op.add_column(
            sa.Column("connection_secret_ref", sa.Text(), nullable=False, server_default="")
        )

    import json

    rows = conn.execute(
        sa.text("SELECT id, connection_config_json, credential_ref FROM source_instances")
    ).fetchall()

    for row_id, cfg_raw, cred_raw in rows:
        try:
            cfg = json.loads(cfg_raw) if cfg_raw else {}
        except Exception:
            cfg = {}
        try:
            cred = json.loads(cred_raw) if cred_raw else {}
        except Exception:
            cred = {}
        merged = json.dumps({**cfg, **cred})
        conn.execute(
            sa.text("UPDATE source_instances SET connection_secret_ref = :v WHERE id = :id"),
            {"v": merged, "id": row_id},
        )

    with op.batch_alter_table("source_instances") as batch_op:
        batch_op.drop_column("credential_ref")
        batch_op.drop_column("connection_config_json")
