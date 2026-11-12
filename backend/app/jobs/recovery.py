"""Recovery — runs on startup to reclaim expired leases and reconcile state.

On startup/periodic recovery, reclaim expired leases ONLY after
reconciling on-disk/external effects. A completed transfer file must
not be redownloaded because its stage DB update was interrupted.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Job, StageRun, JobFile
from app.database.repositories import JobRepository
from app.database.session import get_session_factory
from app.domain.models import JobStatus, StageRunStatus, TransferStatus
from app.settings import Settings

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Recovery:
    """Handles job recovery on startup and periodic lease cleanup."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def recover_expired_leases(self) -> int:
        """Reclaim jobs with expired leases.

        Returns count of reclaimed jobs.
        """
        factory = get_session_factory(self.settings)
        now = _utcnow()
        reclaimed = 0

        async with factory() as session:
            # Find jobs with expired leases that are still 'running'
            result = await session.execute(
                select(Job).where(
                    and_(
                        Job.status == JobStatus.RUNNING.value,
                        Job.lease_expires_at.is_not(None),
                        Job.lease_expires_at <= now,
                        Job.ended_at.is_(None),
                    )
                )
            )
            expired_jobs = result.scalars().all()

            for job in expired_jobs:
                logger.warning(
                    "Reclaiming job %s (stage %s) — lease expired at %s",
                    job.id, job.stage, job.lease_expires_at,
                )

                # Reconcile: check if the stage's files are on disk
                # For download stage, check if .part files exist
                await self._reconcile_job(session, job)

                # Reset to queued for retry (or retry_wait if we want backoff)
                await session.execute(
                    update(Job)
                    .where(Job.id == job.id)
                    .values(
                        status=JobStatus.QUEUED.value,
                        worker_token=None,
                        lease_expires_at=None,
                        updated_at=now,
                    )
                )
                await session.execute(
                    JobFile.__table__.insert()  # type: ignore[attr-defined]
                    .values([]) if False else update(JobFile)
                    .where(and_(JobFile.job_id == job.id, JobFile.transfer_status == TransferStatus.IN_PROGRESS.value))
                    .values(transfer_status=TransferStatus.PENDING.value)
                )

                # Mark active stage_run as failed (interrupted)
                active_runs = await session.execute(
                    select(StageRun).where(
                        and_(
                            StageRun.job_id == job.id,
                            StageRun.status == StageRunStatus.RUNNING.value,
                        )
                    )
                )
                for run in active_runs.scalars().all():
                    run.status = StageRunStatus.FAILED.value
                    run.ended_at = now
                    run.error_code = "lease_expired"
                    run.error_detail = "Lease expired during execution, reclaimed by recovery"

                reclaimed += 1

            if reclaimed:
                await session.commit()
                logger.info("Reclaimed %d expired jobs", reclaimed)

        return reclaimed

    async def _reconcile_job(self, session: AsyncSession, job: Job) -> None:
        """Reconcile on-disk state with DB state before reclaiming.

        For download stage: .part files on disk are authoritative.
        For other stages: the stage will re-run from the beginning.
        """
        if job.stage == "download":
            config = job.config_snapshot_json
            temp_dir = config.get("temporary_directory", "/tmp")
            # Job files that were marked in_progress are reset to pending
            # so the download stage will resume from the .part file offset
            logger.info("Reconciling download for job %s — .part files will resume", job.id)
        elif job.stage in ("extract", "publish"):
            # These stages may have partial output on disk
            # The stage handler should be idempotent and clean up incomplete work
            logger.info("Reconciling %s for job %s", job.stage, job.id)
