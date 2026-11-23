"""In-app SQLite-backed job scheduler.

Polls eligible jobs approximately once per second and dispatches them
according to stage-specific concurrency. Status and claims persist in SQLite.
In-memory semaphores cap actively running stages.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import JobRepository
from app.database.session import get_session_factory
from app.domain.models import JobStage, JobStatus, StageRunStatus
from app.settings import Settings

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StageSemaphore:
    """Asyncio semaphore with a configurable limit that can change at runtime."""

    def __init__(self, initial_limit: int) -> None:
        self._limit = initial_limit
        self._semaphore = asyncio.Semaphore(initial_limit)

    @property
    def limit(self) -> int:
        return self._limit

    def set_limit(self, new_limit: int) -> None:
        """Adjust the limit. Only takes effect for new acquisitions."""
        if new_limit == self._limit:
            return
        # Rebuild semaphore with new limit — existing holders keep running
        old = self._semaphore
        self._limit = new_limit
        self._semaphore = asyncio.Semaphore(new_limit)

    async def acquire(self) -> bool:
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=0.1)
            return True
        except asyncio.TimeoutError:
            return False

    def release(self) -> None:
        self._semaphore.release()

    @property
    def current_value(self) -> int:
        """Approximate available permits (may be stale)."""
        return self._limit  # For reporting only


class JobScheduler:
    """Background task that polls and dispatches jobs from the SQLite queue."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._running = False
        self._task: asyncio.Task | None = None
        self._stage_semaphores: dict[str, StageSemaphore] = {}
        self._active_jobs: dict[str, asyncio.Task] = {}
        self._shutdown_event = asyncio.Event()

        # Initialize stage semaphores
        self._init_semaphores()

    def _init_semaphores(self) -> None:
        """Create semaphores for each stage with configured limits."""
        self._stage_semaphores = {
            JobStage.RESOLVE_SOURCE.value: StageSemaphore(10),  # Lightweight
            JobStage.DOWNLOAD.value: StageSemaphore(self.settings.max_concurrent_download_jobs),
            JobStage.VERIFY.value: StageSemaphore(self.settings.max_concurrent_verify_jobs),
            JobStage.EXTRACT.value: StageSemaphore(self.settings.max_concurrent_extract_jobs),
            JobStage.PUBLISH.value: StageSemaphore(self.settings.max_concurrent_publish_jobs),
            JobStage.INSPECT_IMPORT.value: StageSemaphore(10),  # Lightweight
            JobStage.IMPORT.value: StageSemaphore(self.settings.max_concurrent_import_jobs),
            JobStage.CONFIRM_IMPORT.value: StageSemaphore(10),  # Lightweight
            JobStage.NOTIFY.value: StageSemaphore(10),  # Lightweight
            JobStage.CLEANUP.value: StageSemaphore(10),  # Lightweight
        }

    def update_concurrency_limits(self) -> None:
        """Called when settings change — rebuild semaphores for key stages."""
        stages = {
            JobStage.DOWNLOAD.value: self.settings.max_concurrent_download_jobs,
            JobStage.VERIFY.value: self.settings.max_concurrent_verify_jobs,
            JobStage.EXTRACT.value: self.settings.max_concurrent_extract_jobs,
            JobStage.PUBLISH.value: self.settings.max_concurrent_publish_jobs,
            JobStage.IMPORT.value: self.settings.max_concurrent_import_jobs,
        }
        for stage, limit in stages.items():
            if stage in self._stage_semaphores:
                self._stage_semaphores[stage].set_limit(limit)

    @property
    def active_download_count(self) -> int:
        """Count of currently running download jobs."""
        return len([t for s, t in self._active_jobs.items()
                     if s.startswith(JobStage.DOWNLOAD.value)])

    async def start(self) -> None:
        """Start the scheduler loop."""
        if self._running:
            return
        self._running = True
        self._shutdown_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Job scheduler started")

    async def stop(self) -> None:
        """Graceful shutdown — stop claiming, wait for active jobs."""
        self._running = False
        self._shutdown_event.set()
        if self._task:
            # Give the poll loop a chance to exit
            self._task.cancel()
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._task = None

        # Wait for active jobs to finish (bounded)
        if self._active_jobs:
            logger.info("Waiting for %d active jobs to finish...", len(self._active_jobs))
            for job_id, task in list(self._active_jobs.items()):
                try:
                    await asyncio.wait_for(task, timeout=30.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    logger.warning("Job %s did not finish in time, cancelling", job_id)
                    task.cancel()
            self._active_jobs.clear()

        logger.info("Job scheduler stopped")

    async def _run_loop(self) -> None:
        """Main poll loop — runs once per second."""
        while self._running and not self._shutdown_event.is_set():
            try:
                await self._poll_and_dispatch()
            except Exception:
                logger.exception("Scheduler poll error")
            await asyncio.sleep(1.0)

    async def _poll_and_dispatch(self) -> None:
        """Check each stage for available slots and dispatch eligible jobs."""
        factory = get_session_factory(self.settings)

        for stage in [
            JobStage.RESOLVE_SOURCE.value,
            JobStage.DOWNLOAD.value,
            JobStage.VERIFY.value,
            JobStage.EXTRACT.value,
            JobStage.PUBLISH.value,
            JobStage.INSPECT_IMPORT.value,
            JobStage.IMPORT.value,
            JobStage.CONFIRM_IMPORT.value,
            JobStage.NOTIFY.value,
            JobStage.CLEANUP.value,
        ]:
            semaphore = self._stage_semaphores.get(stage)
            if not semaphore:
                continue

            # Try to acquire a slot
            acquired = await semaphore.acquire()
            if not acquired:
                continue

            # Try to claim a job
            async with factory() as session:
                repo = JobRepository(session)
                worker_token = str(uuid.uuid4())
                lease_until = _utcnow() + timedelta(seconds=self.settings.stage_lease_seconds)
                now = _utcnow()

                try:
                    job = await repo.claim_next(stage, worker_token, lease_until, now)
                except Exception:
                    logger.exception("Claim failed for stage %s", stage)
                    semaphore.release()
                    continue

            if job is None:
                semaphore.release()
                continue

            # Dispatch the job
            task = asyncio.create_task(self._run_job(job.id, stage, worker_token, semaphore))
            self._active_jobs[f"{stage}:{job.id}"] = task

    async def _run_job(self, job_id: str, stage: str, worker_token: str, semaphore: StageSemaphore) -> None:
        """Run a single job stage, then transition to next stage."""
        from app.jobs.runner import JobRunner

        runner = JobRunner(self.settings, job_id, stage, worker_token)
        try:
            result = await runner.execute()
            logger.info("Job %s stage %s completed: %s", job_id, stage, result.status)

            # Transition to next stage
            if result.status == StageRunStatus.SUCCEEDED:
                await self._transition_success(job_id, stage)
            elif result.status == StageRunStatus.SKIPPED:
                await self._transition_skipped(job_id, stage)
            elif result.status == StageRunStatus.FAILED:
                await self._transition_failed(job_id, stage, result.error_code, result.error_detail, result.retryable)
            elif result.status == StageRunStatus.NEEDS_ATTENTION:
                await self._transition_needs_attention(job_id, stage, result.error_code, result.error_detail)

        except asyncio.CancelledError:
            logger.info("Job %s stage %s cancelled", job_id, stage)
            await self._transition_cancelled(job_id, stage)
        except Exception:
            logger.exception("Job %s stage %s crashed", job_id, stage)
            await self._transition_failed(job_id, stage, "unexpected_error", "Unhandled exception", False)
        finally:
            semaphore.release()
            key = f"{stage}:{job_id}"
            self._active_jobs.pop(key, None)

    async def _transition_success(self, job_id: str, stage: str) -> None:
        """Move job to next stage on success."""
        factory = get_session_factory(self.settings)
        async with factory() as session:
            repo = JobRepository(session)
            next_stage = _get_next_stage(stage)
            if next_stage is None:
                # Last stage — mark completed
                await repo.update(
                    job_id,
                    status=JobStatus.COMPLETED.value,
                    ended_at=_utcnow(),
                    worker_token=None,
                    lease_expires_at=None,
                )
                await repo.add_event(
                    job_id=job_id,
                    severity="info",
                    kind="job.completed",
                    message="Job completed successfully",
                )
            else:
                await repo.update(
                    job_id,
                    status=JobStatus.QUEUED.value,
                    stage=next_stage,
                    worker_token=None,
                    lease_expires_at=None,
                    attempts=0,
                )
                await repo.add_event(
                    job_id=job_id,
                    severity="info",
                    kind="stage.completed",
                    stage=stage,
                    message=f"Stage {stage} succeeded, transitioning to {next_stage}",
                )
            await session.commit()

    async def _transition_skipped(self, job_id: str, stage: str) -> None:
        """Skip optional stage and move to next."""
        await self._transition_success(job_id, stage)  # Same logic

    async def _transition_failed(
        self, job_id: str, stage: str, error_code: str, error_detail: str, retryable: bool
    ) -> None:
        """Handle stage failure — retry or mark needs_attention."""
        factory = get_session_factory(self.settings)
        async with factory() as session:
            repo = JobRepository(session)

            # Get current job to check attempts
            job = await repo.get(job_id)
            if not job:
                return

            attempts = job.attempts + 1

            if retryable and attempts < self.settings.retry_limit:
                # Exponential backoff with jitter
                backoff = min(2 ** attempts + random.uniform(0, 5), 300)
                next_run = _utcnow() + timedelta(seconds=backoff)
                await repo.update(
                    job_id,
                    status=JobStatus.RETRY_WAIT.value,
                    attempts=attempts,
                    next_run_at=next_run,
                    worker_token=None,
                    lease_expires_at=None,
                    error_code=error_code,
                    error_detail=error_detail,
                )
                await repo.add_event(
                    job_id=job_id,
                    severity="warning",
                    kind="stage.retry",
                    stage=stage,
                    message=f"Stage {stage} failed: {error_detail}. Retry in {backoff:.0f}s (attempt {attempts})",
                    details_json={"error_code": error_code, "backoff_seconds": backoff},
                )
            else:
                # Max retries reached or not retryable
                await repo.update(
                    job_id,
                    status=JobStatus.NEEDS_ATTENTION.value,
                    error_code=error_code,
                    error_detail=error_detail,
                    worker_token=None,
                    lease_expires_at=None,
                )
                await repo.add_event(
                    job_id=job_id,
                    severity="error",
                    kind="stage.failed",
                    stage=stage,
                    message=f"Stage {stage} failed permanently: {error_detail}",
                    details_json={"error_code": error_code},
                )
            await session.commit()

    async def _transition_needs_attention(self, job_id: str, stage: str, error_code: str, error_detail: str) -> None:
        """Mark job as needing attention."""
        factory = get_session_factory(self.settings)
        async with factory() as session:
            repo = JobRepository(session)
            # No fetch config: wait on the seedbox; saving fetch requeues the job
            waiting = error_code == "no_transfer_config"
            await repo.update(
                job_id,
                status=(JobStatus.WAITING_SOURCE if waiting else JobStatus.NEEDS_ATTENTION).value,
                error_code=error_code,
                error_detail=error_detail,
                worker_token=None,
                lease_expires_at=None,
            )
            await repo.add_event(
                job_id=job_id,
                severity="info" if waiting else "error",
                kind="stage.waiting_fetch" if waiting else "stage.needs_attention",
                stage=stage,
                message=error_detail if waiting else f"Stage {stage} needs attention: {error_detail}",
                details_json={"error_code": error_code},
            )
            await session.commit()

    async def _transition_cancelled(self, job_id: str, stage: str) -> None:
        """Handle job cancellation during execution."""
        factory = get_session_factory(self.settings)
        async with factory() as session:
            repo = JobRepository(session)
            await repo.update(
                job_id,
                status=JobStatus.PAUSED.value,
                worker_token=None,
                lease_expires_at=None,
            )
            await repo.add_event(
                job_id=job_id,
                severity="info",
                kind="stage.cancelled",
                stage=stage,
                message=f"Stage {stage} cancelled",
            )
            await session.commit()


# ---------------------------------------------------------------------------
# Stage ordering
# ---------------------------------------------------------------------------

_STAGE_ORDER = [
    JobStage.RESOLVE_SOURCE.value,
    JobStage.DOWNLOAD.value,
    JobStage.VERIFY.value,
    JobStage.EXTRACT.value,
    JobStage.PUBLISH.value,
    JobStage.INSPECT_IMPORT.value,
    JobStage.IMPORT.value,
    JobStage.CONFIRM_IMPORT.value,
    JobStage.NOTIFY.value,
    JobStage.CLEANUP.value,
]


def _get_next_stage(current_stage: str) -> str | None:
    """Return the next stage after the current one, or None if last."""
    try:
        idx = _STAGE_ORDER.index(current_stage)
    except ValueError:
        return None
    if idx + 1 < len(_STAGE_ORDER):
        return _STAGE_ORDER[idx + 1]
    return None
