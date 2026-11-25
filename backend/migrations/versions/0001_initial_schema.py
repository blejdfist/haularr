"""Initial schema baseline.

Pre-baseline development databases must be recreated.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "library_instances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("adapter_type", sa.String(length=50), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("api_key_secret_ref", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "transfer_instances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("adapter_type", sa.String(length=50), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "source_instances",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("adapter_type", sa.String(length=50), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("connection_config_json", sa.JSON(), nullable=False),
        sa.Column("credential_ref", sa.Text(), nullable=False),
        sa.Column("default_transfer_id", sa.String(length=36), nullable=True),
        sa.Column("poll_interval", sa.Integer(), nullable=False),
        sa.Column("onboarding_state", sa.String(length=50), nullable=False),
        sa.Column("initial_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scan_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["default_transfer_id"],
            ["transfer_instances.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "transfer_endpoints",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("transfer_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("tls_settings_json", sa.JSON(), nullable=False),
        sa.Column("credential_ref", sa.Text(), nullable=False),
        sa.Column("path_mappings_json", sa.JSON(), nullable=False),
        sa.Column("health_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["transfer_id"],
            ["transfer_instances.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "source_label_rules",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("automatic_processing", sa.Boolean(), nullable=False),
        sa.Column("temporary_directory", sa.Text(), nullable=False),
        sa.Column("completed_directory", sa.Text(), nullable=False),
        sa.Column("library_instance_id", sa.String(length=36), nullable=True),
        sa.Column("transfer_override_id", sa.String(length=36), nullable=True),
        sa.Column("pipeline_options_json", sa.JSON(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["library_instance_id"],
            ["library_instances.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_instances.id"],
        ),
        sa.ForeignKeyConstraint(
            ["transfer_override_id"],
            ["transfer_instances.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "label", name="uq_source_label"),
    )
    op.create_table(
        "source_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("remote_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("labels_json", sa.JSON(), nullable=False),
        sa.Column("source_status", sa.String(length=50), nullable=False),
        sa.Column("remote_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_eligibility", sa.String(length=50), nullable=True),
        sa.Column("eligible_rule_id", sa.String(length=36), nullable=True),
        sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("infohash", sa.String(length=255), nullable=True),
        sa.Column("remote_metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["eligible_rule_id"],
            ["source_label_rules.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source_instances.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "remote_id", name="uq_source_remote"),
    )
    op.create_index(
        "ix_source_items_source_completed",
        "source_items",
        ["source_id", "completed_at"],
        unique=False,
    )
    op.create_table(
        "eligibility_checks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_item_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=True),
        sa.Column("result", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("was_manual_override", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["source_label_rules.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_item_id"],
            ["source_items.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_item_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("config_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_token", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("download_bytes_total", sa.Integer(), nullable=False),
        sa.Column("download_bytes_done", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(
            ["rule_id"],
            ["source_label_rules.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_item_id"],
            ["source_items.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_lease_expires", "jobs", ["lease_expires_at"], unique=False)
    op.create_index("ix_jobs_source_item", "jobs", ["source_item_id"], unique=False)
    op.create_index(
        "ix_jobs_status_stage_next_run",
        "jobs",
        ["status", "stage", "next_run_at", "priority", "created_at"],
        unique=False,
    )
    op.create_table(
        "media_matches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_item_id", sa.String(length=36), nullable=False),
        sa.Column("library_instance_id", sa.String(length=36), nullable=True),
        sa.Column("media_type", sa.String(length=50), nullable=False),
        sa.Column("catalog_id", sa.Integer(), nullable=True),
        sa.Column("episode_ids_json", sa.JSON(), nullable=False),
        sa.Column("parse_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("ambiguous", sa.Boolean(), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["library_instance_id"],
            ["library_instances.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_item_id"],
            ["source_items.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "file_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_relpath", sa.Text(), nullable=False),
        sa.Column("library_instance_id", sa.String(length=36), nullable=True),
        sa.Column("library_media_id", sa.Integer(), nullable=True),
        sa.Column("inspection_json", sa.JSON(), nullable=False),
        sa.Column("import_request_json", sa.JSON(), nullable=False),
        sa.Column("external_command_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["library_instance_id"],
            ["library_instances.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "job_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_events_job_created", "job_events", ["job_id", "created_at"], unique=False
    )
    op.create_table(
        "job_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("remote_relpath", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("remote_identity_json", sa.JSON(), nullable=False),
        sa.Column("local_relpath", sa.Text(), nullable=True),
        sa.Column("bytes_received", sa.Integer(), nullable=False),
        sa.Column("checksum_type", sa.String(length=20), nullable=True),
        sa.Column("checksum", sa.String(length=255), nullable=True),
        sa.Column("transfer_status", sa.String(length=50), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "stage_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress_json", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_stage_runs_job_stage", "stage_runs", ["job_id", "stage"], unique=False)
    op.create_index(
        "ix_jobs_one_active_per_item",
        "jobs",
        ["source_item_id"],
        unique=True,
        sqlite_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_stage_runs_job_stage", table_name="stage_runs")
    op.drop_table("stage_runs")
    op.drop_table("notification_deliveries")
    op.drop_table("job_files")
    op.drop_index("ix_job_events_job_created", table_name="job_events")
    op.drop_table("job_events")
    op.drop_table("file_imports")
    op.drop_table("media_matches")
    op.drop_index("ix_jobs_status_stage_next_run", table_name="jobs")
    op.drop_index("ix_jobs_source_item", table_name="jobs")
    op.drop_index("ix_jobs_lease_expires", table_name="jobs")
    op.drop_index("ix_jobs_one_active_per_item", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("eligibility_checks")
    op.drop_index("ix_source_items_source_completed", table_name="source_items")
    op.drop_table("source_items")
    op.drop_table("source_label_rules")
    op.drop_table("transfer_endpoints")
    op.drop_table("source_instances")
    op.drop_table("users")
    op.drop_table("transfer_instances")
    op.drop_table("library_instances")
    op.drop_table("app_settings")
