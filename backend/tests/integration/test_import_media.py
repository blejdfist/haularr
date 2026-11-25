"""Test library import flow with mocked Arr adapters.

Acceptance criteria:
9. Potential upgrade without definitive Arr preflight is not auto-downloaded;
   post-transfer manual import rejects unsafe upgrades without overwriting.
23. Library state changes between queue and import are handled safely.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.domain.models import (
    ImportCandidate,
    ImportInspection,
    ImportOperation,
    ImportOutcome,
    MediaMatch,
    MediaType,
)
from app.processing.import_media import run_import_stage


class FakeLibraryAdapter:
    """Fake library adapter for testing."""

    def __init__(
        self,
        inspection: ImportInspection | None = None,
        operation: ImportOperation | None = None,
        outcome: ImportOutcome | None = None,
    ):
        self._inspection = inspection
        self._operation = operation
        self._outcome = outcome

    async def inspect_import(self, ready_path: str, match: MediaMatch) -> ImportInspection:
        return self._inspection or ImportInspection(candidates=[], all_rejected=True)

    async def submit_import(
        self, candidates: list, *, download_id: str | None = None
    ) -> ImportOperation:
        return self._operation or ImportOperation(
            operation_id="op_123",
            command_id=42,
            submitted_at=datetime.now(UTC),
            candidates=[c.absolute_path for c in candidates],
        )

    async def reconcile_import(
        self, operation: ImportOperation, match: MediaMatch
    ) -> ImportOutcome:
        return self._outcome or ImportOutcome(success=True, imported_paths=operation.candidates)


@pytest.mark.asyncio
async def test_import_accepted_candidates():
    """Accepted candidates are imported successfully."""
    match = MediaMatch(media_type=MediaType.SERIES, catalog_id=1, title="Test Show")

    inspection = ImportInspection(
        candidates=[
            ImportCandidate(
                relative_path="/path/file1.mkv",
                absolute_path="/path/file1.mkv",
                quality="WEBDL-1080p",
                rejection_reasons=[],
                media_id=1,
                episode_ids=[1],
            ),
            ImportCandidate(
                relative_path="/path/file2.mkv",
                absolute_path="/path/file2.mkv",
                quality="WEBDL-1080p",
                rejection_reasons=["Not a quality upgrade"],
                media_id=1,
                episode_ids=[2],
            ),
        ],
        all_rejected=False,
    )

    adapter = FakeLibraryAdapter(
        inspection=inspection,
        outcome=ImportOutcome(
            success=True,
            imported_paths=["/path/file1.mkv"],
        ),
    )

    result = await run_import_stage(adapter, "/path", match)

    # Partial: the rejected file stays on disk for the user, so the job must not reach cleanup.
    assert not result.success
    assert result.partial
    assert len(result.imported_paths) == 1
    assert len(result.rejected_paths) == 1
    assert "file2.mkv" in result.error and "Not a quality upgrade" in result.error


@pytest.mark.asyncio
async def test_import_rejected_sample_is_not_partial():
    """A rejected sample is junk: the import still counts as done."""
    match = MediaMatch(media_type=MediaType.MOVIE, catalog_id=1, title="Test Movie")
    inspection = ImportInspection(
        candidates=[
            ImportCandidate(relative_path="/p/movie.mkv", absolute_path="/p/movie.mkv", media_id=1),
            ImportCandidate(
                relative_path="/p/sample.mkv",
                absolute_path="/p/sample.mkv",
                rejection_reasons=["Sample"],
                media_id=1,
            ),
        ],
        all_rejected=False,
    )
    result = await run_import_stage(FakeLibraryAdapter(inspection=inspection), "/p", match)
    assert result.success and not result.partial


@pytest.mark.asyncio
async def test_import_all_rejected():
    """All-rejected candidates result in failure."""
    match = MediaMatch(media_type=MediaType.MOVIE, catalog_id=1, title="Test Movie")

    inspection = ImportInspection(
        candidates=[
            ImportCandidate(
                relative_path="/path/file.mkv",
                absolute_path="/path/file.mkv",
                rejection_reasons=["Not an upgrade", "Wrong quality"],
            ),
        ],
        all_rejected=True,
    )

    adapter = FakeLibraryAdapter(inspection=inspection)

    result = await run_import_stage(adapter, "/path", match)

    assert not result.success
    assert len(result.rejected_paths) == 1
    assert "Not an upgrade" in result.error or "rejected" in result.error.lower()


@pytest.mark.asyncio
async def test_import_pending():
    """Import that is still in progress returns pending=True."""
    match = MediaMatch(media_type=MediaType.SERIES, catalog_id=1, title="Test Show")

    inspection = ImportInspection(
        candidates=[
            ImportCandidate(
                relative_path="/path/file.mkv",
                absolute_path="/path/file.mkv",
                rejection_reasons=[],
            ),
        ],
        all_rejected=False,
    )

    adapter = FakeLibraryAdapter(
        inspection=inspection,
        outcome=ImportOutcome(
            success=False,
            details={"pending": True, "command_status": "running"},
        ),
    )

    result = await run_import_stage(adapter, "/path", match, timeout=0)

    assert not result.success
    assert result.pending is True
    assert "progress" in result.error.lower()


@pytest.mark.asyncio
async def test_import_no_candidates():
    """No candidates found results in failure."""
    match = MediaMatch(media_type=MediaType.MOVIE, catalog_id=1, title="Test Movie")

    adapter = FakeLibraryAdapter(
        inspection=ImportInspection(candidates=[], all_rejected=True),
    )

    result = await run_import_stage(adapter, "/path", match)

    assert not result.success
    assert "No import candidates" in result.error or "All" in result.error
