"""Retention — prune terminal jobs after configured N days.

Rules:
- Delete terminal Jobs and their stage/file/event rows after completed_history_days
- Keep Source Item inventory and Source Label configurations
- Failed or attention Jobs are NOT silently purged under completed-job retention
- Never delete Path B media by purging database history
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    FileImport,
    Job,
    JobEvent,
    JobFile,
    NotificationDelivery,
    StageRun,
)
from app.settings import Settings

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


# Terminal statuses that are safe to prune under completed-job retention
_PRUNABLE_STATUSES = [
    "completed",
    "completed_with_warnings",
    "skipped",
    "cancelled",
]

# Failed/attention jobs are NOT pruned under completed-job retention
_PROTECTED_STATUSES = [
    "failed",
    "needs_attention",
]


class RetentionJob:
    """Periodic retention job that prunes old terminal jobs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def run_once(self) -> dict[str, int]:
        """Run retention once and return counts of pruned records.

        Returns dict with counts: jobs, stage_runs, job_files, events, file_imports, notifications.
        """
        cutoff = _utcnow() - timedelta(days=self.settings.completed_history_days)
        counts: dict[str, int] = {
            "jobs": 0,
            "stage_runs": 0,
            "job_files": 0,
            "events": 0,
            "file_imports": 0,
            "notifications": 0,
        }

        from app.database.session import get_session_factory

        factory = get_session_factory(self.settings)

        async with factory() as session:
            # Find prunable jobs: terminal, ended_at older than cutoff, NOT failed/attention
            result = await session.execute(
                select(Job).where(
                    and_(
                        Job.status.in_(_PRUNABLE_STATUSES),
                        Job.ended_at.is_not(None),
                        Job.ended_at <= cutoff,
                    )
                )
            )
            jobs_to_prune = result.scalars().all()

            if not jobs_to_prune:
                return counts

            job_ids = [j.id for j in jobs_to_prune]
            counts["jobs"] = len(job_ids)

            counts.update(await delete_jobs(session, job_ids))
            await session.commit()

            logger.info(
                "Retention pruned %d jobs (older than %d days): %s",
                counts["jobs"],
                self.settings.completed_history_days,
                {k: v for k, v in counts.items() if k != "jobs"},
            )

        return counts

    async def run_periodic(self, interval_seconds: int = 3600) -> None:
        """Run retention periodically. Intended as a background task."""
        import asyncio

        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Retention job error")
            await asyncio.sleep(interval_seconds)


async def delete_jobs(session: AsyncSession, job_ids: list[str]) -> dict[str, int]:
    """Delete jobs and every row that hangs off them (children first, for the foreign keys)."""
    counts: dict[str, int] = {}
    for key, model in (
        ("stage_runs", StageRun),
        ("job_files", JobFile),
        ("file_imports", FileImport),
        ("events", JobEvent),
        ("notifications", NotificationDelivery),
    ):
        result = await session.execute(delete(model).where(model.job_id.in_(job_ids)))
        counts[key] = result.rowcount or 0
    await session.execute(delete(Job).where(Job.id.in_(job_ids)))
    return counts
