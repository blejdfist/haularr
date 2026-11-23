"""Domain DTOs, enums, and invariants.

These are pure Python dataclasses/Pydantic models with NO SQLAlchemy or HTTP
payload dependencies. Adapters translate to/from these.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SourceStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ERROR = "error"


class EligibilityStatus(str, Enum):
    UNKNOWN = "unknown"
    UNROUTED = "unrouted"
    WAITING_SOURCE_COMPLETION = "waiting_source_completion"
    CLASSIFYING = "classifying"
    WAITING_LIBRARY = "waiting_library"
    NOT_REGISTERED = "not_registered"
    NEEDS_REVIEW = "needs_review"
    MISSING = "missing"
    PARTIALLY_MISSING = "partially_missing"
    ALREADY_AVAILABLE = "already_available"
    UNCONFIRMED_UPGRADE = "unconfirmed_upgrade"
    UPGRADE_ELIGIBLE = "upgrade_eligible"
    IGNORED = "ignored"
    DOWNLOAD_NEEDED = "download_needed"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_SOURCE = "waiting_source"
    WAITING_EXTERNAL = "waiting_external"
    RETRY_WAIT = "retry_wait"
    PAUSED = "paused"
    NEEDS_ATTENTION = "needs_attention"
    FAILED = "failed"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class JobStage(str, Enum):
    RESOLVE_SOURCE = "resolve_source"
    DOWNLOAD = "download"
    VERIFY = "verify"
    EXTRACT = "extract"
    PUBLISH = "publish"
    INSPECT_IMPORT = "inspect_import"
    IMPORT = "import"
    CONFIRM_IMPORT = "confirm_import"
    NOTIFY = "notify"
    CLEANUP = "cleanup"


class StageRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    SKIPPED = "skipped"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    NEEDS_ATTENTION = "needs_attention"


class MediaType(str, Enum):
    SERIES = "series"
    MOVIE = "movie"
    UNKNOWN = "unknown"


class TransferStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    VERIFIED = "verified"


class OnboardingState(str, Enum):
    PENDING = "pending"           # Initial scan not yet done
    SCANNING = "scanning"         # Currently scanning
    AWAITING_REVIEW = "awaiting_review"  # Scan done; admin must acknowledge
    COMPLETED = "completed"       # Admin acknowledged; auto-processing enabled


class AdapterType(str, Enum):
    RTORRENT = "rtorrent"
    FTPS = "ftps"
    SONARR = "sonarr"
    RADARR = "radarr"


# ---------------------------------------------------------------------------
# Source Adapter DTOs
# ---------------------------------------------------------------------------


class RemoteFileDTO(BaseModel):
    """Normalized file entry from a source manifest."""

    relative_path: str
    size_bytes: int
    content_hash: str | None = None
    hash_type: str | None = None  # e.g. "sha1", "md5"
    path_hints: dict[str, Any] = Field(default_factory=dict)


class SourceItemDTO(BaseModel):
    """Normalized representation of one download in a source instance."""

    remote_id: str
    name: str
    labels: list[str] = Field(default_factory=list)
    status: SourceStatus
    completed_at: datetime | None = None
    total_bytes: int = 0
    remote_base_path: str = ""
    infohash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Transfer Adapter DTOs
# ---------------------------------------------------------------------------


class RemoteManifest(BaseModel):
    """Files confirmed present on the remote transfer endpoint."""

    endpoint_name: str
    files: list[RemoteFileDTO]
    checked_at: datetime


class TransferResult(BaseModel):
    """Outcome of transferring a single file."""

    success: bool
    bytes_transferred: int
    resumed_from: int = 0
    error: str | None = None
    endpoint_name: str = ""


# ---------------------------------------------------------------------------
# Library Adapter DTOs
# ---------------------------------------------------------------------------


class MediaMatch(BaseModel):
    """Result of parsing a release name against a library."""

    media_type: MediaType
    catalog_id: int | None = None       # Sonarr series_id or Radarr movie_id
    title: str = ""
    year: int | None = None
    episode_ids: list[int] = Field(default_factory=list)
    parse_data: dict[str, Any] = Field(default_factory=dict)
    # Library records returned by /parse (Sonarr: {"episodes": [...]}, Radarr: {"movie": {...}})
    library_record: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    ambiguous: bool = False


class LibraryInventory(BaseModel):
    """Library presence for a matched title."""

    catalog_id: int
    title: str
    registered: bool
    has_file: bool
    episode_counts: dict[str, int] = Field(default_factory=dict)  # season -> count
    missing_episode_ids: list[int] = Field(default_factory=list)
    existing_quality: str | None = None


class EligibilityDecision(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class EligibilityAssessment(BaseModel):
    """Quality upgrade eligibility decision from a Library Adapter."""

    decision: EligibilityDecision
    evidence: dict[str, Any] = Field(default_factory=dict)
    capability_used: str = ""


class ImportCandidate(BaseModel):
    """A file candidate for library import."""

    relative_path: str
    absolute_path: str
    quality: str = ""
    custom_formats: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)
    media_id: int | None = None
    episode_ids: list[int] = Field(default_factory=list)


class ImportInspection(BaseModel):
    """Result of inspecting files in Path B for import."""

    candidates: list[ImportCandidate] = Field(default_factory=list)
    all_rejected: bool = False
    inspection_data: dict[str, Any] = Field(default_factory=dict)


class ImportOperation(BaseModel):
    """An import operation submitted to Sonarr/Radarr."""

    operation_id: str
    command_id: int | None = None
    submitted_at: datetime
    candidates: list[str] = Field(default_factory=list)


class ImportOutcome(BaseModel):
    """Confirmed result of a library import operation."""

    success: bool
    imported_paths: list[str] = Field(default_factory=list)
    rejected_paths: list[str] = Field(default_factory=list)
    skipped_paths: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Configuration snapshots (stored with jobs)
# ---------------------------------------------------------------------------


class JobConfigSnapshot(BaseModel):
    """Immutable config captured at job creation time."""

    source_id: str
    source_name: str
    label: str
    transfer_id: str
    library_instance_id: str | None
    temporary_directory: str
    completed_directory: str
    retry_limit: int
    stage_lease_seconds: int
