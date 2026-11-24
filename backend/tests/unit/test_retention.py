"""Test the retention job — prune old terminal jobs.

Acceptance criteria:
28. Jobs in failed/needs_attention are not silently deleted by completed-history retention.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.database.models import Job, SourceItem, SourceLabelRule, SourceInstance, JobEvent, StageRun
from app.database.repositories import JobRepository, SourceRepository, LabelRuleRepository, SourceItemRepository
from app.domain.models import JobStage, JobStatus
from app.jobs.retention import RetentionJob


@pytest.mark.asyncio
async def test_retention_prunes_old_completed_jobs(app, settings):
    """Completed jobs older than retention_days are pruned."""
    from app.database.session import get_session_factory

    factory = get_session_factory(settings)

    # Create a source + label + item + old completed job
    async with factory() as session:
        source_repo = SourceRepository(session)
        source = await source_repo.create(
            name="Test",
            adapter_type="rtorrent",
            connection_config_json={}, credential_ref="",
        )
        label_repo = LabelRuleRepository(session)
        rule = await label_repo.create(
            source_id=source.id,
            label="tv",
            temporary_directory="/tmp",
            completed_directory="/tmp",
        )
        item_repo = SourceItemRepository(session)
        item, _ = await item_repo.upsert(
            source_id=source.id,
            remote_id="hash1",
            title="Test.Show",
            labels_json=["tv"],
            source_status="completed",
        )

        job_repo = JobRepository(session)
        old_time = datetime.now(timezone.utc) - timedelta(days=30)
        job = await job_repo.create(
            source_item_id=item.id,
            rule_id=rule.id,
            config_snapshot_json={},
            status=JobStatus.COMPLETED.value,
            stage=JobStage.CLEANUP.value,
            ended_at=old_time,
        )
        await job_repo.add_event(
            job_id=job.id,
            severity="info",
            kind="job.completed",
            message="Done",
        )
        await session.commit()
        job_id = job.id

    # Run retention with 14 day cutoff
    retention = RetentionJob(settings)
    counts = await retention.run_once()

    assert counts["jobs"] == 1

    # Verify job is gone
    async with factory() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_retention_preserves_failed_jobs(app, settings):
    """Failed jobs are NOT pruned by completed-history retention."""
    from app.database.session import get_session_factory

    factory = get_session_factory(settings)

    async with factory() as session:
        source_repo = SourceRepository(session)
        source = await source_repo.create(
            name="Test",
            adapter_type="rtorrent",
            connection_config_json={}, credential_ref="",
        )
        label_repo = LabelRuleRepository(session)
        rule = await label_repo.create(
            source_id=source.id,
            label="tv",
            temporary_directory="/tmp",
            completed_directory="/tmp",
        )
        item_repo = SourceItemRepository(session)
        item, _ = await item_repo.upsert(
            source_id=source.id,
            remote_id="hash1",
            title="Test.Show",
            labels_json=["tv"],
            source_status="completed",
        )

        job_repo = JobRepository(session)
        old_time = datetime.now(timezone.utc) - timedelta(days=30)
        job = await job_repo.create(
            source_item_id=item.id,
            rule_id=rule.id,
            config_snapshot_json={},
            status=JobStatus.FAILED.value,
            stage=JobStage.TRANSFER.value,
            ended_at=old_time,
        )
        await session.commit()
        job_id = job.id

    retention = RetentionJob(settings)
    counts = await retention.run_once()

    assert counts["jobs"] == 0

    # Verify job still exists
    async with factory() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_retention_preserves_needs_attention_jobs(app, settings):
    """needs_attention jobs are NOT pruned."""
    from app.database.session import get_session_factory

    factory = get_session_factory(settings)

    async with factory() as session:
        source_repo = SourceRepository(session)
        source = await source_repo.create(
            name="Test",
            adapter_type="rtorrent",
            connection_config_json={}, credential_ref="",
        )
        label_repo = LabelRuleRepository(session)
        rule = await label_repo.create(
            source_id=source.id,
            label="tv",
            temporary_directory="/tmp",
            completed_directory="/tmp",
        )
        item_repo = SourceItemRepository(session)
        item, _ = await item_repo.upsert(
            source_id=source.id,
            remote_id="hash1",
            title="Test.Show",
            labels_json=["tv"],
            source_status="completed",
        )

        job_repo = JobRepository(session)
        old_time = datetime.now(timezone.utc) - timedelta(days=30)
        job = await job_repo.create(
            source_item_id=item.id,
            rule_id=rule.id,
            config_snapshot_json={},
            status=JobStatus.NEEDS_ATTENTION.value,
            stage=JobStage.IMPORT.value,
            ended_at=old_time,
        )
        await session.commit()
        job_id = job.id

    retention = RetentionJob(settings)
    counts = await retention.run_once()

    assert counts["jobs"] == 0

    async with factory() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_retention_preserves_recent_completed(app, settings):
    """Recently completed jobs are NOT pruned."""
    from app.database.session import get_session_factory

    factory = get_session_factory(settings)

    async with factory() as session:
        source_repo = SourceRepository(session)
        source = await source_repo.create(
            name="Test",
            adapter_type="rtorrent",
            connection_config_json={}, credential_ref="",
        )
        label_repo = LabelRuleRepository(session)
        rule = await label_repo.create(
            source_id=source.id,
            label="tv",
            temporary_directory="/tmp",
            completed_directory="/tmp",
        )
        item_repo = SourceItemRepository(session)
        item, _ = await item_repo.upsert(
            source_id=source.id,
            remote_id="hash1",
            title="Test.Show",
            labels_json=["tv"],
            source_status="completed",
        )

        job_repo = JobRepository(session)
        recent_time = datetime.now(timezone.utc) - timedelta(days=1)
        job = await job_repo.create(
            source_item_id=item.id,
            rule_id=rule.id,
            config_snapshot_json={},
            status=JobStatus.COMPLETED.value,
            stage=JobStage.CLEANUP.value,
            ended_at=recent_time,
        )
        await session.commit()
        job_id = job.id

    retention = RetentionJob(settings)
    counts = await retention.run_once()

    assert counts["jobs"] == 0

    async with factory() as session:
        result = await session.execute(select(Job).where(Job.id == job_id))
        assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_retention_preserves_source_items(app, settings):
    """Source items are never pruned by job retention."""
    from app.database.session import get_session_factory

    factory = get_session_factory(settings)

    async with factory() as session:
        source_repo = SourceRepository(session)
        source = await source_repo.create(
            name="Test",
            adapter_type="rtorrent",
            connection_config_json={}, credential_ref="",
        )
        label_repo = LabelRuleRepository(session)
        rule = await label_repo.create(
            source_id=source.id,
            label="tv",
            temporary_directory="/tmp",
            completed_directory="/tmp",
        )
        item_repo = SourceItemRepository(session)
        item, _ = await item_repo.upsert(
            source_id=source.id,
            remote_id="hash1",
            title="Test.Show",
            labels_json=["tv"],
            source_status="completed",
        )

        job_repo = JobRepository(session)
        old_time = datetime.now(timezone.utc) - timedelta(days=30)
        await job_repo.create(
            source_item_id=item.id,
            rule_id=rule.id,
            config_snapshot_json={},
            status=JobStatus.COMPLETED.value,
            stage=JobStage.CLEANUP.value,
            ended_at=old_time,
        )
        await session.commit()
        source_id = source.id
        item_id = item.id

    retention = RetentionJob(settings)
    await retention.run_once()

    # Source and item still exist
    async with factory() as session:
        result = await session.execute(select(SourceInstance).where(SourceInstance.id == source_id))
        assert result.scalar_one_or_none() is not None

        result = await session.execute(select(SourceItem).where(SourceItem.id == item_id))
        assert result.scalar_one_or_none() is not None
