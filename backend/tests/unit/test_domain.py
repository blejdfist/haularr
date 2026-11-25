"""Test domain models and enums."""

from __future__ import annotations

from app.domain.models import (
    AdapterType,
    EligibilityStatus,
    JobStage,
    JobStatus,
    OnboardingState,
    RemoteFileDTO,
    SourceItemDTO,
    SourceStatus,
)


def test_source_status_enum():
    assert SourceStatus.ACTIVE == "active"
    assert SourceStatus.COMPLETED == "completed"
    assert SourceStatus.STOPPED == "stopped"
    assert SourceStatus.ERROR == "error"


def test_eligibility_status_values():
    assert EligibilityStatus.UNKNOWN == "unknown"
    assert EligibilityStatus.UNROUTED == "unrouted"
    assert EligibilityStatus.NOT_REGISTERED == "not_registered"
    assert EligibilityStatus.MISSING == "missing"
    assert EligibilityStatus.ALREADY_AVAILABLE == "already_available"
    assert EligibilityStatus.IGNORED == "ignored"


def test_job_stage_order():
    assert [s.value for s in JobStage] == [
        "source_download",
        "check_library",
        "transfer",
        "verify",
        "extract",
        "move",
        "inspect_import",
        "import",
        "cleanup",
    ]


def test_job_status_values():
    assert JobStatus.QUEUED == "queued"
    assert JobStatus.RUNNING == "running"
    assert JobStatus.FAILED == "failed"
    assert JobStatus.COMPLETED == "completed"
    assert JobStatus.PAUSED == "paused"
    assert JobStatus.NEEDS_ATTENTION == "needs_attention"
    assert JobStatus.CANCELLED == "cancelled"


def test_source_item_dto():
    dto = SourceItemDTO(
        remote_id="abc123",
        name="Test.Release",
        labels=["tv"],
        status=SourceStatus.COMPLETED,
        total_bytes=1000,
    )
    assert dto.remote_id == "abc123"
    assert dto.labels == ["tv"]
    assert dto.status == SourceStatus.COMPLETED


def test_remote_file_dto():
    f = RemoteFileDTO(
        relative_path="release/file.mkv",
        size_bytes=1000000,
    )
    assert f.relative_path == "release/file.mkv"
    assert f.size_bytes == 1000000


def test_onboarding_states():
    assert OnboardingState.PENDING == "pending"
    assert OnboardingState.COMPLETED == "completed"
    assert OnboardingState.AWAITING_REVIEW == "awaiting_review"


def test_adapter_types():
    assert AdapterType.RTORRENT == "rtorrent"
    assert AdapterType.FTPS == "ftps"
    assert AdapterType.SONARR == "sonarr"
    assert AdapterType.RADARR == "radarr"
