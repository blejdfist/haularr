"""SQLAlchemy ORM models for Haularr.

All times are stored as timezone-aware UTC timestamps.
Primary keys use string ULIDs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, DateTime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Source configuration
# ---------------------------------------------------------------------------


class SourceInstance(Base):
    __tablename__ = "source_instances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(50), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Non-secret connection config: host/url, port, username, tls settings
    connection_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    # Encrypted credential reference: Fernet-encrypted password/token, stored as "enc:<blob>"
    credential_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_transfer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transfer_instances.id"), nullable=True
    )
    poll_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    onboarding_state: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )
    initial_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scan_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    label_rules: Mapped[list[SourceLabelRule]] = relationship(
        "SourceLabelRule", back_populates="source", cascade="all, delete-orphan"
    )
    source_items: Mapped[list[SourceItem]] = relationship(
        "SourceItem", back_populates="source"
    )


class SourceLabelRule(Base):
    __tablename__ = "source_label_rules"
    __table_args__ = (
        UniqueConstraint("source_id", "label", name="uq_source_label"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_instances.id"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    automatic_processing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    temporary_directory: Mapped[str] = mapped_column(Text, nullable=False)
    completed_directory: Mapped[str] = mapped_column(Text, nullable=False)
    library_instance_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("library_instances.id"), nullable=True
    )
    transfer_override_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transfer_instances.id"), nullable=True
    )
    pipeline_options_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    source: Mapped[SourceInstance] = relationship("SourceInstance", back_populates="label_rules")
    library_instance: Mapped[LibraryInstance | None] = relationship("LibraryInstance")


# ---------------------------------------------------------------------------
# Transfer configuration
# ---------------------------------------------------------------------------


class TransferInstance(Base):
    __tablename__ = "transfer_instances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(50), nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    endpoints: Mapped[list[TransferEndpoint]] = relationship(
        "TransferEndpoint", back_populates="transfer", cascade="all, delete-orphan"
    )


class TransferEndpoint(Base):
    __tablename__ = "transfer_endpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    transfer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("transfer_instances.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=21)
    tls_settings_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    credential_ref: Mapped[str] = mapped_column(Text, nullable=False)
    path_mappings_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    health_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    transfer: Mapped[TransferInstance] = relationship("TransferInstance", back_populates="endpoints")


# ---------------------------------------------------------------------------
# Library configuration
# ---------------------------------------------------------------------------


class LibraryInstance(Base):
    __tablename__ = "library_instances"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_secret_ref: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    options_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


# ---------------------------------------------------------------------------
# Source items (inventory)
# ---------------------------------------------------------------------------


class SourceItem(Base):
    __tablename__ = "source_items"
    __table_args__ = (
        UniqueConstraint("source_id", "remote_id", name="uq_source_remote"),
        Index("ix_source_items_source_completed", "source_id", "completed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_instances.id"), nullable=False
    )
    remote_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    labels_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_status: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    remote_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_eligibility: Mapped[str | None] = mapped_column(String(50), nullable=True)
    eligible_rule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_label_rules.id"), nullable=True
    )
    ignored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    infohash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remote_metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )

    source: Mapped[SourceInstance] = relationship("SourceInstance", back_populates="source_items")
    jobs: Mapped[list[Job]] = relationship(
        "Job", back_populates="source_item", cascade="all, delete-orphan"
    )
    media_matches: Mapped[list[MediaMatch]] = relationship(
        "MediaMatch", back_populates="source_item", cascade="all, delete-orphan"
    )
    eligibility_checks: Mapped[list[EligibilityCheck]] = relationship(
        "EligibilityCheck", back_populates="source_item", cascade="all, delete-orphan"
    )


class MediaMatch(Base):
    __tablename__ = "media_matches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    source_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_items.id"), nullable=False
    )
    library_instance_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("library_instances.id"), nullable=True
    )
    media_type: Mapped[str] = mapped_column(String(50), nullable=False, default="unknown")
    catalog_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_ids_json: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    parse_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    ambiguous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    source_item: Mapped[SourceItem] = relationship("SourceItem", back_populates="media_matches")


class EligibilityCheck(Base):
    __tablename__ = "eligibility_checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    source_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_items.id"), nullable=False
    )
    rule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_label_rules.id"), nullable=True
    )
    result: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    was_manual_override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    source_item: Mapped[SourceItem] = relationship(
        "SourceItem", back_populates="eligibility_checks"
    )


# ---------------------------------------------------------------------------
# Jobs and stages
# ---------------------------------------------------------------------------


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status_stage_next_run", "status", "stage", "next_run_at", "priority", "created_at"),
        Index("ix_jobs_lease_expires", "lease_expires_at"),
        Index("ix_jobs_source_item", "source_item_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    source_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_items.id"), nullable=False
    )
    rule_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("source_label_rules.id"), nullable=False
    )
    config_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(50), nullable=False, default="resolve_source")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    download_bytes_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    download_bytes_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    source_item: Mapped[SourceItem] = relationship("SourceItem", back_populates="jobs")
    stage_runs: Mapped[list[StageRun]] = relationship(
        "StageRun", back_populates="job", cascade="all, delete-orphan"
    )
    job_files: Mapped[list[JobFile]] = relationship(
        "JobFile", back_populates="job", cascade="all, delete-orphan"
    )
    file_imports: Mapped[list[FileImport]] = relationship(
        "FileImport", back_populates="job", cascade="all, delete-orphan"
    )
    events: Mapped[list[JobEvent]] = relationship(
        "JobEvent", back_populates="job", cascade="all, delete-orphan"
    )
    notification_deliveries: Mapped[list[NotificationDelivery]] = relationship(
        "NotificationDelivery", cascade="all, delete-orphan"
    )


class StageRun(Base):
    __tablename__ = "stage_runs"
    __table_args__ = (
        Index("ix_stage_runs_job_stage", "job_id", "stage"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id"), nullable=False
    )
    stage: Mapped[str] = mapped_column(String(50), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    progress_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    job: Mapped[Job] = relationship("Job", back_populates="stage_runs")


class JobFile(Base):
    __tablename__ = "job_files"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id"), nullable=False
    )
    remote_relpath: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remote_identity_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    local_relpath: Mapped[str | None] = mapped_column(Text, nullable=True)
    bytes_received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checksum_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transfer_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[Job] = relationship("Job", back_populates="job_files")


class FileImport(Base):
    __tablename__ = "file_imports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id"), nullable=False
    )
    candidate_relpath: Mapped[str] = mapped_column(Text, nullable=False)
    library_instance_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("library_instances.id"), nullable=True
    )
    library_media_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inspection_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    import_request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    external_command_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    job: Mapped[Job] = relationship("Job", back_populates="file_imports")


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (
        Index("ix_job_events_job_created", "job_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    kind: Mapped[str] = mapped_column(String(100), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    job: Mapped[Job] = relationship("Job", back_populates="events")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id"), nullable=False
    )
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# App settings (key-value)
# ---------------------------------------------------------------------------


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


# ---------------------------------------------------------------------------
# SQLite PRAGMA setup via event
# ---------------------------------------------------------------------------


@event.listens_for(Base.metadata, "after_create")
def set_sqlite_pragmas(target, connection, **kwargs):  # type: ignore[no-untyped-def]
    """Set SQLite pragmas for safety and performance."""
    connection.execute(text("PRAGMA foreign_keys=ON"))
    connection.execute(text("PRAGMA journal_mode=WAL"))
    connection.execute(text("PRAGMA busy_timeout=5000"))
