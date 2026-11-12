"""Job runner — executes a single job stage.

Each stage implementation is idempotent and reconcileable.
Stages run outside the DB transaction; progress is persisted periodically.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database.repositories import JobRepository
from app.database.session import get_session_factory
from app.domain.models import JobStage, StageRunStatus, TransferStatus
from app.settings import Settings

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class StageResult:
    """Result of running a single stage."""

    status: StageRunStatus
    error_code: str = ""
    error_detail: str = ""
    retryable: bool = True
    progress: dict[str, Any] = None


class JobRunner:
    """Runs a single job stage."""

    def __init__(self, settings: Settings, job_id: str, stage: str, worker_token: str) -> None:
        self.settings = settings
        self.job_id = job_id
        self.stage = stage
        self.worker_token = worker_token
        self._heartbeat_task: asyncio.Task | None = None
        self._cancelled = False

    async def execute(self) -> StageResult:
        """Execute the stage and return the result."""
        factory = get_session_factory(self.settings)

        # Create stage_run record
        async with factory() as session:
            repo = JobRepository(session)
            job = await repo.get(self.job_id)
            if not job:
                return StageResult(StageRunStatus.FAILED, "job_not_found", "Job not found", False)

            attempt = job.attempts
            stage_run = await repo.add_stage_run(
                job_id=self.job_id,
                stage=self.stage,
                attempt=attempt + 1,
                status=StageRunStatus.RUNNING.value,
                started_at=_utcnow(),
            )
            await session.commit()

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            # Dispatch to stage handler
            handler = self._get_stage_handler()
            result = await handler(job, stage_run.id)
            return result
        finally:
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def _heartbeat_loop(self) -> None:
        """Update lease periodically."""
        interval = max(self.settings.stage_lease_seconds // 4, 15)
        factory = get_session_factory(self.settings)
        while True:
            await asyncio.sleep(interval)
            try:
                async with factory() as session:
                    repo = JobRepository(session)
                    job = await repo.get(self.job_id)
                    if job and job.worker_token == self.worker_token:
                        lease_until = _utcnow() + datetime.timedelta(
                            seconds=self.settings.stage_lease_seconds
                        )
                        await repo.update(
                            self.job_id,
                            lease_expires_at=lease_until,
                            updated_at=_utcnow(),
                        )
                        await session.commit()
            except Exception:
                logger.debug("Heartbeat failed for job %s", self.job_id)

    def _get_stage_handler(self) -> Any:
        """Return the handler function for the current stage."""
        handlers = {
            JobStage.RESOLVE_SOURCE.value: self._stage_resolve_source,
            JobStage.DOWNLOAD.value: self._stage_download,
            JobStage.VERIFY.value: self._stage_verify,
            JobStage.EXTRACT.value: self._stage_extract,
            JobStage.PUBLISH.value: self._stage_publish,
            JobStage.INSPECT_IMPORT.value: self._stage_inspect_import,
            JobStage.IMPORT.value: self._stage_import,
            JobStage.CONFIRM_IMPORT.value: self._stage_confirm_import,
            JobStage.NOTIFY.value: self._stage_notify,
            JobStage.CLEANUP.value: self._stage_cleanup,
        }
        return handlers.get(self.stage, self._stage_unknown)

    # -----------------------------------------------------------------------
    # Stage implementations
    # -----------------------------------------------------------------------

    async def _stage_resolve_source(self, job: Any, stage_run_id: str) -> StageResult:
        """Validate that files are available on the transfer endpoint."""
        config = job.config_snapshot_json
        transfer_id = config.get("transfer_id")
        if not transfer_id:
            return StageResult(
                StageRunStatus.FAILED, "no_transfer_config", "No transfer configured", False
            )

        # Get source item and manifest
        factory = get_session_factory(self.settings)
        async with factory() as session:
            repo = JobRepository(session)
            from app.database.repositories import SourceItemRepository
            item_repo = SourceItemRepository(session)
            item = await item_repo.get(job.source_item_id)
            if not item:
                return StageResult(
                    StageRunStatus.FAILED, "item_not_found", "Source item not found", False
                )

            # Check if source reports completed
            if item.source_status != "completed":
                return StageResult(
                    StageRunStatus.NEEDS_ATTENTION,
                    "source_not_complete",
                    f"Source item status is {item.source_status}, not completed",
                    True,  # Retryable — may complete later
                )

        # In M2, we just validate config and mark ready for download
        # The actual file inspection happens in the download stage
        await self._update_progress(stage_run_id, {"status": "resolved"})
        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_download(self, job: Any, stage_run_id: str) -> StageResult:
        """Transfer files from the remote endpoint to Path A."""
        config = job.config_snapshot_json
        transfer_id = config.get("transfer_id")
        temp_dir = config.get("temporary_directory", "/tmp")
        if not transfer_id:
            return StageResult(
                StageRunStatus.FAILED, "no_transfer_config", "No transfer configured", False
            )

        factory = get_session_factory(self.settings)

        # Get source item
        async with factory() as session:
            from app.database.repositories import SourceItemRepository
            item_repo = SourceItemRepository(session)
            item = await item_repo.get(job.source_item_id)
            if not item:
                return StageResult(
                    StageRunStatus.FAILED, "item_not_found", "Source item not found", False
                )

            # Get transfer config
            from app.database.repositories import TransferRepository
            transfer_repo = TransferRepository(session)
            transfer = await transfer_repo.get(transfer_id)
            if not transfer:
                return StageResult(
                    StageRunStatus.FAILED, "transfer_not_found", "Transfer not found", False
                )

            # Get source adapter to fetch file manifest
            import json
            from app.adapters.sources import create_source_adapter
            from app.security import decrypt_secret

            # Get source instance for adapter config
            from app.database.repositories import SourceRepository
            source_repo = SourceRepository(session)
            source = await source_repo.get(item.source_id)
            if not source:
                return StageResult(
                    StageRunStatus.FAILED, "source_not_found", "Source not found", False
                )

            # Parse source connection config
            try:
                source_config = json.loads(source.connection_secret_ref)
            except (json.JSONDecodeError, TypeError):
                source_config = {}

            # Get transfer endpoints
            endpoints = transfer.endpoints if hasattr(transfer, "endpoints") else []

            # Build source adapter and get manifest
            source_adapter = create_source_adapter(
                source.id, source.adapter_type, source_config
            )

            # Get file manifest from source adapter
            try:
                manifest = await source_adapter.get_manifest(item.remote_id)
            except Exception as exc:
                logger.error("Failed to get file manifest: %s", exc)
                return StageResult(
                    StageRunStatus.FAILED, "manifest_error", str(exc), True
                )

            if not manifest:
                return StageResult(
                    StageRunStatus.NEEDS_ATTENTION,
                    "no_files",
                    "No completed files found in source manifest",
                    True,
                )

            # Create job_files records
            job_repo = JobRepository(session)
            from app.database.models import JobFile

            existing_files = {f.remote_relpath: f for f in job.job_files} if hasattr(job, 'job_files') else {}

            total_bytes = sum(f.size_bytes for f in manifest)
            await job_repo.update(self.job_id, download_bytes_total=total_bytes)
            await session.commit()

        # Download each file
        # Use the transfer adapter to download files to Path A
        sanitized_title = _sanitize_dirname(item.title)
        local_base = Path(temp_dir) / sanitized_title
        local_base.mkdir(parents=True, exist_ok=True)

        bytes_done = 0
        for file_dto in manifest:
            if self._cancelled:
                return StageResult(StageRunStatus.FAILED, "cancelled", "Download cancelled", False)

            local_path = local_base / file_dto.relative_path
            local_path.parent.mkdir(parents=True, exist_ok=True)
            part_path = str(local_path) + ".part"

            # Check for existing .part file for resume
            resume_offset = 0
            if os.path.exists(part_path):
                resume_offset = os.path.getsize(part_path)
                logger.info("Resuming %s from offset %d", file_dto.relative_path, resume_offset)

            # Build transfer config from first available endpoint
            if not endpoints:
                return StageResult(
                    StageRunStatus.FAILED, "no_endpoints",
                    "No transfer endpoints configured", False
                )

            endpoint = endpoints[0]  # For now, use first endpoint

            # Build transfer adapter config
            transfer_config = dict(transfer.config_json)
            if "host" not in transfer_config and endpoint:
                transfer_config["host"] = endpoint.host
                transfer_config["port"] = endpoint.port

            from app.adapters.transfers import create_transfer_adapter
            transfer_adapter = create_transfer_adapter(
                transfer_id, transfer.adapter_type, transfer_config
            )

            def progress_cb(received: int, total: int) -> None:
                nonlocal bytes_done
                bytes_done = received + (bytes_done - received) if False else bytes_done
                # We'll persist progress in batch

            # Transfer the file
            result = await transfer_adapter.transfer_file(
                remote_file=file_dto,
                remote_base_path=item.remote_path,
                destination_part_path=part_path,
                resume_offset=resume_offset,
                progress_callback=progress_cb,
                path_mappings=endpoint.path_mappings_json if endpoint else None,
            )

            if not result.success:
                return StageResult(
                    StageRunStatus.FAILED,
                    "transfer_failed",
                    result.error or "Transfer failed",
                    True,
                )

            # Verify size
            if os.path.exists(part_path):
                actual_size = os.path.getsize(part_path)
                if actual_size != file_dto.size_bytes:
                    logger.warning(
                        "Size mismatch for %s: expected %d got %d",
                        file_dto.relative_path, file_dto.size_bytes, actual_size
                    )
                    return StageResult(
                        StageRunStatus.FAILED,
                        "size_mismatch",
                        f"File {file_dto.relative_path} size mismatch",
                        True,
                    )

                # Atomic rename .part → final
                os.rename(part_path, str(local_path))

            # Update job_files in DB
            async with factory() as session:
                job_repo = JobRepository(session)
                job_file = JobFile(
                    job_id=self.job_id,
                    remote_relpath=file_dto.relative_path,
                    size_bytes=file_dto.size_bytes,
                    local_relpath=file_dto.relative_path,
                    bytes_received=file_dto.size_bytes,
                    transfer_status=TransferStatus.COMPLETED.value,
                    verified_at=_utcnow(),
                )
                session.add(job_file)
                bytes_done += file_dto.size_bytes
                await job_repo.update(
                    self.job_id,
                    download_bytes_done=bytes_done,
                )
                await self._update_progress(stage_run_id, {
                    "file": file_dto.relative_path,
                    "bytes_done": bytes_done,
                    "bytes_total": total_bytes,
                })
                await session.commit()

        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_verify(self, job: Any, stage_run_id: str) -> StageResult:
        """Verify transferred files (SFV check, size check)."""
        # M3 will implement full SFV verification
        # For M2, just check sizes
        factory = get_session_factory(self.settings)
        async with factory() as session:
            repo = JobRepository(session)
            job = await repo.get(self.job_id)
            for f in job.job_files:
                if f.transfer_status != TransferStatus.COMPLETED.value:
                    return StageResult(
                        StageRunStatus.FAILED, "incomplete_files",
                        f"File {f.remote_relpath} not fully transferred", True
                    )
            await session.commit()

        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_extract(self, job: Any, stage_run_id: str) -> StageResult:
        """Extract archives (RAR/ZIP). M3 will implement full extraction."""
        # Check if any files are archives
        archive_exts = {".rar", ".zip", ".r00", ".r01"}
        has_archives = any(
            Path(f.remote_relpath).suffix.lower() in archive_exts
            for f in job.job_files if hasattr(job, 'job_files')
        )
        if not has_archives:
            return StageResult(StageRunStatus.SKIPPED)

        # M3 will implement extraction
        return StageResult(StageRunStatus.SKIPPED)

    async def _stage_publish(self, job: Any, stage_run_id: str) -> StageResult:
        """Publish prepared files from Path A to Path B."""
        # M3 will implement full publish with copy + atomic rename
        config = job.config_snapshot_json
        temp_dir = config.get("temporary_directory", "/tmp")
        completed_dir = config.get("completed_directory", "/tmp")

        # For M2, just create the directory structure
        sanitized_title = _sanitize_dirname(item_title_from_job(job))
        Path(completed_dir, sanitized_title).mkdir(parents=True, exist_ok=True)

        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_inspect_import(self, job: Any, stage_run_id: str) -> StageResult:
        """Inspect import candidates. M3 will implement."""
        config = job.config_snapshot_json
        if not config.get("library_instance_id"):
            return StageResult(StageRunStatus.SKIPPED)
        # M3 will implement
        return StageResult(StageRunStatus.SKIPPED)

    async def _stage_import(self, job: Any, stage_run_id: str) -> StageResult:
        """Submit import to library. M3 will implement."""
        return StageResult(StageRunStatus.SKIPPED)

    async def _stage_confirm_import(self, job: Any, stage_run_id: str) -> StageResult:
        """Confirm import completed. M3 will implement."""
        return StageResult(StageRunStatus.SKIPPED)

    async def _stage_notify(self, job: Any, stage_run_id: str) -> StageResult:
        """Send notifications. M3 will implement."""
        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_cleanup(self, job: Any, stage_run_id: str) -> StageResult:
        """Clean up temporary files. M3 will implement full cleanup."""
        config = job.config_snapshot_json
        temp_dir = config.get("temporary_directory", "/tmp")
        library_id = config.get("library_instance_id")

        # Only clean Path A; Path B is final if no library
        if not library_id:
            return StageResult(StageRunStatus.SUCCEEDED)

        # M3 will implement safe cleanup
        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_unknown(self, job: Any, stage_run_id: str) -> StageResult:
        """Unknown stage handler."""
        return StageResult(
            StageRunStatus.FAILED, "unknown_stage", f"Unknown stage: {self.stage}", False
        )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def _update_progress(self, stage_run_id: str, progress: dict[str, Any]) -> None:
        """Update stage_run progress in DB."""
        factory = get_session_factory(self.settings)
        async with factory() as session:
            from sqlalchemy import update
            from app.database.models import StageRun

            await session.execute(
                update(StageRun)
                .where(StageRun.id == stage_run_id)
                .values(progress_json=progress, updated_at=_utcnow())
            )
            await session.commit()


def _sanitize_dirname(name: str) -> str:
    """Sanitize a release name for use as a directory name."""
    # Remove illegal characters for most filesystems
    sanitized = name.replace("/", "_").replace("\\", "_").replace(":", "_")
    sanitized = sanitized.replace("<", "_").replace(">", "_").replace("|", "_")
    sanitized = sanitized.replace("?", "").replace("*", "").replace('"', "_")
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip(". ")
    return sanitized[:200]  # Limit length


def item_title_from_job(job: Any) -> str:
    """Extract title from job's source item."""
    return job.config_snapshot_json.get("title", job.source_item_id)
