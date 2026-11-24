"""Creating jobs and tracking the seedbox download stage.

A job exists from the first scan that sees a tagged torrent. While the torrent
downloads on the seedbox the job sits in ``source_download`` with status
``waiting_source``; no worker runs it. Discovery writes the torrent's progress
into that stage's run on every scan and moves the job to ``check_library``
once the seedbox is done.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Job, SourceItem, SourceLabelRule, StageRun
from app.database.repositories import JobRepository, SourceRepository
from app.domain.models import JobStage, JobStatus, RemoteFileDTO, SourceStatus
from app.logging_buffer import named
from app.settings import Settings

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def item_complete(item: SourceItem) -> bool:
    """Done on the seedbox. rTorrent reports a paused, unfinished torrent as stopped too."""
    if item.source_status == SourceStatus.COMPLETED.value:
        return True
    return item.source_status == SourceStatus.STOPPED.value and bool(
        (item.remote_metadata_json or {}).get("complete", True)
    )


def initial_position(item: SourceItem) -> tuple[str, str]:
    """(stage, status) a new or restarted job starts at."""
    if item_complete(item):
        return JobStage.CHECK_LIBRARY.value, JobStatus.QUEUED.value
    return JobStage.SOURCE_DOWNLOAD.value, JobStatus.WAITING_SOURCE.value


async def start_download_run(session: AsyncSession, job_id: str) -> None:
    """Open the source_download run that discovery writes progress into."""
    session.add(StageRun(
        job_id=job_id, stage=JobStage.SOURCE_DOWNLOAD.value, attempt=1,
        status="running", started_at=_utcnow(), progress_json={},
    ))
    await session.flush()


async def create_job(
    session: AsyncSession,
    item: SourceItem,
    rule: SourceLabelRule,
    settings: Settings,
    *,
    approved: bool,
    kind: str,
    message: str,
) -> Job:
    """Create the job for an item. ``approved``: the user asked for it, so a manual rule won't stop it."""
    source = await SourceRepository(session).get(item.source_id)
    config_snapshot = {
        "source_id": item.source_id,
        "source_name": source.name if source else "",
        "label": rule.label,
        "transfer_id": rule.transfer_override_id or (source.default_transfer_id if source else None),
        "library_instance_id": rule.library_instance_id,
        "temporary_directory": rule.temporary_directory,
        "completed_directory": rule.completed_directory,
        "retry_limit": settings.retry_limit,
        "stage_lease_seconds": settings.stage_lease_seconds,
        "title": item.title,
        "approved": approved,
    }
    stage, status = initial_position(item)
    job_repo = JobRepository(session)
    job = await job_repo.create(
        source_item_id=item.id,
        rule_id=rule.id,
        config_snapshot_json=config_snapshot,
        priority=rule.priority,
        status=status,
        stage=stage,
    )
    if stage == JobStage.SOURCE_DOWNLOAD.value:
        await start_download_run(session, job.id)
    await job_repo.add_event(
        job_id=job.id, severity="info", kind=kind, message=message,
        details_json={"eligibility": item.last_eligibility},
    )
    logger.info("Created job %s (label=%s, stage=%s)", named(item.title, job.id), rule.label, stage)
    return job


async def update_download(
    session: AsyncSession, job: Job, item: SourceItem, files: list[RemoteFileDTO] | None
) -> None:
    """Record the seedbox's progress for a downloading job; hand it to the scheduler once done."""
    run = (await session.execute(
        select(StageRun)
        .where(StageRun.job_id == job.id, StageRun.stage == JobStage.SOURCE_DOWNLOAD.value)
        .order_by(StageRun.started_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if run is None:  # e.g. a job restarted before this stage existed
        await start_download_run(session, job.id)
        return await update_download(session, job, item, files)

    meta: dict[str, Any] = item.remote_metadata_json or {}
    progress: dict[str, Any] = {
        "bytes_done": int(meta.get("completed_bytes", 0)),
        "bytes_total": item.size_bytes,
        "bps": int(meta.get("down_rate", 0)),
        "message": meta.get("message", ""),
    }
    if files is not None:
        progress["files"] = [
            {"path": f.relative_path, "size_bytes": f.size_bytes, "done_bytes": f.done_bytes or 0}
            for f in files
        ]
    run.progress_json = progress

    if item_complete(item):
        run.status = "succeeded"
        run.ended_at = _utcnow()
        job.stage = JobStage.CHECK_LIBRARY.value
        job.status = JobStatus.QUEUED.value
        await JobRepository(session).add_event(
            job_id=job.id, severity="info", kind="stage.completed",
            stage=JobStage.SOURCE_DOWNLOAD.value, message="Download on the seedbox finished",
        )
    await session.flush()
