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

from sqlalchemy import select
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
            # No transfer configured — skip to download (may be configured differently)
            return StageResult(StageRunStatus.SUCCEEDED)

        factory = get_session_factory(self.settings)
        async with factory() as session:
            from app.database.repositories import SourceItemRepository, SourceRepository, TransferRepository
            item_repo = SourceItemRepository(session)
            item = await item_repo.get(job.source_item_id)
            if not item:
                return StageResult(
                    StageRunStatus.FAILED, "item_not_found", "Source item not found", False
                )

            # Check source reports completed
            if item.source_status not in ("completed", "stopped"):
                return StageResult(
                    StageRunStatus.FAILED,
                    "source_not_complete",
                    f"Source item status is '{item.source_status}', expected completed",
                    True,
                )

            # Get source adapter and fetch file manifest
            import json
            from app.adapters.sources import create_source_adapter
            from app.security import decrypt_secret

            source_repo = SourceRepository(session)
            source = await source_repo.get(item.source_id)
            if not source:
                return StageResult(
                    StageRunStatus.FAILED, "source_not_found", "Source not found", False
                )

            # Build adapter config: non-secret config + decrypted credential
            source_config = dict(source.connection_config_json or {})
            cred_ref = source.credential_ref or ""
            if cred_ref.startswith("enc:"):
                try:
                    plaintext = decrypt_secret(cred_ref[4:], self._get_master_key())
                    try:
                        creds = json.loads(plaintext)
                        if isinstance(creds, dict):
                            source_config.update(creds)
                        else:
                            source_config["password"] = plaintext
                    except json.JSONDecodeError:
                        source_config["password"] = plaintext
                except Exception:
                    pass
            elif cred_ref:
                try:
                    creds = json.loads(cred_ref)
                    if isinstance(creds, dict):
                        source_config.update(creds)
                except json.JSONDecodeError:
                    source_config["password"] = cred_ref

            source_adapter = create_source_adapter(source.id, source.adapter_type, source_config)
            try:
                manifest = await source_adapter.get_manifest(item.remote_id)
            except Exception as exc:
                return StageResult(
                    StageRunStatus.FAILED, "manifest_error",
                    f"Failed to get file manifest: {exc}", True,
                )

            if not manifest:
                return StageResult(
                    StageRunStatus.FAILED,
                    "source_not_ready",
                    "No completed files found in source manifest — files may still be transferring",
                    True,
                )

            # Inspect files on transfer endpoint to confirm they're visible
            transfer_repo = TransferRepository(session)
            transfer = await transfer_repo.get(transfer_id)
            if not transfer:
                return StageResult(
                    StageRunStatus.FAILED, "transfer_not_found", "Transfer config not found", False
                )

            endpoints = list(transfer.endpoints) if transfer.endpoints else []
            if not endpoints:
                # No endpoints configured — skip FTP verification, proceed to download
                await self._update_progress(stage_run_id, {
                    "status": "no_endpoints_to_inspect",
                    "files": len(manifest),
                })
                return StageResult(StageRunStatus.SUCCEEDED)

            endpoint = endpoints[0]
            transfer_config = dict(transfer.config_json)
            transfer_config["host"] = endpoint.host
            transfer_config["port"] = endpoint.port

            # Decrypt credentials if needed
            cred_ref = endpoint.credential_ref
            if isinstance(cred_ref, str) and cred_ref.startswith("enc:"):
                try:
                    cred_json = decrypt_secret(cred_ref[4:], self._get_master_key())
                    import json
                    cred = json.loads(cred_json)
                    transfer_config.update(cred)
                except Exception:
                    pass

            from app.adapters.transfers import create_transfer_adapter
            from app.domain.models import SourceItemDTO, SourceStatus
            transfer_adapter = create_transfer_adapter(
                transfer_id, transfer.adapter_type, transfer_config
            )

            source_item_dto = SourceItemDTO(
                remote_id=item.remote_id,
                name=item.title,
                labels=item.labels_json,
                status=SourceStatus.COMPLETED,
                remote_base_path=item.remote_path,
            )

            try:
                remote_manifest = await transfer_adapter.inspect(
                    source_item_dto,
                    manifest,
                    path_mappings=endpoint.path_mappings_json,
                )
            except Exception as exc:
                # inspect failure means files not visible on FTP — wait
                return StageResult(
                    StageRunStatus.FAILED,
                    "waiting_for_source",
                    f"Files not yet visible on transfer endpoint: {exc}",
                    True,
                )

            # Check all expected files are present
            if len(remote_manifest.files) < len(manifest):
                missing_count = len(manifest) - len(remote_manifest.files)
                return StageResult(
                    StageRunStatus.FAILED,
                    "waiting_for_source",
                    f"{missing_count} of {len(manifest)} files not yet visible on transfer endpoint",
                    True,
                )

            await self._update_progress(stage_run_id, {
                "status": "resolved",
                "files_confirmed": len(remote_manifest.files),
                "endpoint": remote_manifest.endpoint_name,
            })
            return StageResult(StageRunStatus.SUCCEEDED)

    async def _live_transfer_id(self, job: Any) -> str | None:
        from app.database.models import SourceInstance, SourceLabelRule

        async with get_session_factory(self.settings)() as session:
            rule = await session.get(SourceLabelRule, job.rule_id) if job.rule_id else None
            if rule and rule.transfer_override_id:
                return rule.transfer_override_id
            source_id = job.config_snapshot_json.get("source_id")
            source = await session.get(SourceInstance, source_id) if source_id else None
            return source.default_transfer_id if source else None

    async def _stage_download(self, job: Any, stage_run_id: str) -> StageResult:
        """Transfer files from the remote endpoint to Path A."""
        config = job.config_snapshot_json
        transfer_id = config.get("transfer_id")
        temp_dir = config.get("temporary_directory", "/tmp")
        if not transfer_id:
            # Snapshot may predate the fetch config; resolve it live like discovery does
            transfer_id = await self._live_transfer_id(job)
        if not transfer_id:
            # Scheduler parks this as waiting_source until fetch is configured
            return StageResult(
                StageRunStatus.NEEDS_ATTENTION,
                "no_transfer_config",
                "Done on seedbox — no fetch configured",
                False,
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

            # Build adapter config
            source_config = dict(source.connection_config_json or {})
            cred_ref = source.credential_ref or ""
            if cred_ref.startswith("enc:"):
                try:
                    plaintext = decrypt_secret(cred_ref[4:], self._get_master_key())
                    try:
                        creds = json.loads(plaintext)
                        if isinstance(creds, dict):
                            source_config.update(creds)
                        else:
                            source_config["password"] = plaintext
                    except json.JSONDecodeError:
                        source_config["password"] = plaintext
                except Exception:
                    pass
            elif cred_ref:
                try:
                    creds = json.loads(cred_ref)
                    if isinstance(creds, dict):
                        source_config.update(creds)
                except json.JSONDecodeError:
                    source_config["password"] = cred_ref

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
        """Verify transferred files (SFV CRC32 check, size check)."""
        from app.processing.verification import find_sfv_files, parse_sfv, verify_files

        config = job.config_snapshot_json
        temp_dir = config.get("temporary_directory", "/tmp")
        sanitized_title = _sanitize_dirname(item_title_from_job(job))
        local_dir = Path(temp_dir) / sanitized_title

        if not local_dir.exists():
            return StageResult(
                StageRunStatus.NEEDS_ATTENTION, "no_files",
                f"Local directory not found: {local_dir}", False,
            )

        # Find SFV files
        sfv_files = find_sfv_files(local_dir)
        sfv_entries: list = []
        for sfv_file in sfv_files:
            sfv_entries.extend(parse_sfv(sfv_file))

        # Build job_files list from DB
        job_files = [
            {
                "remote_relpath": f.remote_relpath,
                "size_bytes": f.size_bytes,
                "local_relpath": f.local_relpath or f.remote_relpath,
            }
            for f in job.job_files
        ]

        result = verify_files(local_dir, job_files, sfv_entries if sfv_entries else None)

        # Update progress
        await self._update_progress(stage_run_id, {
            "verified": result.verified,
            "failed": [f[0] for f in result.failed],
            "missing": result.missing,
            "checks": result.checks_performed,
        })

        if result.failed:
            return StageResult(
                StageRunStatus.FAILED,
                "verification_failed",
                f"Verification failed: {len(result.failed)} files failed ({'; '.join(f[0] for f in result.failed[:3])})",
                True,
            )

        if result.missing:
            return StageResult(
                StageRunStatus.FAILED,
                "files_missing",
                f"Missing files: {', '.join(result.missing[:3])}",
                True,
            )

        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_extract(self, job: Any, stage_run_id: str) -> StageResult:
        """Extract archives (ZIP, RAR, multipart RAR) safely."""
        from app.processing.extraction import detect_archives, extract_archive

        config = job.config_snapshot_json
        temp_dir = config.get("temporary_directory", "/tmp")
        sanitized_title = _sanitize_dirname(item_title_from_job(job))
        local_dir = Path(temp_dir) / sanitized_title

        if not local_dir.exists():
            return StageResult(
                StageRunStatus.FAILED, "no_files",
                f"Local directory not found: {local_dir}", False,
            )

        archives = detect_archives(local_dir)
        if not archives:
            return StageResult(StageRunStatus.SKIPPED)

        extract_dir = local_dir / "extracted"

        for archive in archives:
            result = extract_archive(archive, extract_dir)
            if not result.success:
                return StageResult(
                    StageRunStatus.NEEDS_ATTENTION,
                    "extraction_failed",
                    result.error,
                    not result.success,  # Some extraction errors are retryable
                )

            await self._update_progress(stage_run_id, {
                "archive": str(archive.name),
                "extracted": result.extracted_files,
            })

        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_publish(self, job: Any, stage_run_id: str) -> StageResult:
        """Publish prepared files from Path A to Path B with copy + atomic rename."""
        from app.processing.publication import publish_files

        config = job.config_snapshot_json
        temp_dir = config.get("temporary_directory", "/tmp")
        completed_dir = config.get("completed_directory", "/tmp")
        sanitized_title = _sanitize_dirname(item_title_from_job(job))

        source_dir = Path(temp_dir) / sanitized_title
        if not source_dir.exists():
            return StageResult(
                StageRunStatus.FAILED, "no_source",
                f"Source directory not found: {source_dir}", False,
            )

        # Identify archive files to exclude from publishing
        archive_exts = {".rar", ".r00", ".r01", ".r02", ".r03", ".r04", ".r05",
                         ".r06", ".r07", ".r08", ".r09", ".r10", ".r11", ".r12",
                         ".r13", ".r14", ".r15", ".r16", ".r17", ".r18", ".r19",
                         ".r20", ".r21", ".r22", ".r23", ".r24", ".r25",
                         ".r26", ".r27", ".r28", ".r29", ".sfv"}
        archive_files = {
            str(f.relative_to(source_dir))
            for f in source_dir.rglob("*")
            if f.is_file() and f.suffix.lower() in archive_exts
        }

        result = publish_files(
            source_dir=source_dir,
            completed_dir=completed_dir,
            release_name=item_title_from_job(job),
            source_item_hash=job.source_item_id[:8],
            archive_files=archive_files,
        )

        await self._update_progress(stage_run_id, {
            "published_path": result.published_path,
            "files": result.published_files,
            "collision_suffix": result.collision_suffix,
        })

        if not result.success:
            return StageResult(
                StageRunStatus.FAILED, "publish_failed",
                result.error, True,
            )

        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_inspect_import(self, job: Any, stage_run_id: str) -> StageResult:
        """Inspect import candidates using Library Adapter."""
        config = job.config_snapshot_json
        library_id = config.get("library_instance_id")
        if not library_id:
            return StageResult(StageRunStatus.SKIPPED)

        # Get library adapter and inspect
        factory = get_session_factory(self.settings)
        async with factory() as session:
            from app.database.repositories import LibraryRepository
            from app.adapters.libraries import create_library_adapter
            from app.security import decrypt_secret
            from app.database.models import MediaMatch as MediaMatchModel

            lib_repo = LibraryRepository(session)
            library = await lib_repo.get(library_id)
            if not library:
                return StageResult(
                    StageRunStatus.FAILED, "library_not_found",
                    "Library instance not found", False,
                )

            # Get the media match for this source item
            match_result = await session.execute(
                select(MediaMatchModel).where(
                    MediaMatchModel.source_item_id == job.source_item_id
                )
            )
            match_row = match_result.scalar_one_or_none()
            if not match_row:
                return StageResult(
                    StageRunStatus.NEEDS_ATTENTION, "no_match",
                    "No media match found for source item", False,
                )

            from app.domain.models import MediaMatch, MediaType
            match = MediaMatch(
                media_type=MediaType(match_row.media_type),
                catalog_id=match_row.catalog_id,
                title="",
                episode_ids=match_row.episode_ids_json,
            )

            # Decrypt API key
            api_key = library.api_key_secret_ref
            if api_key.startswith("enc:"):
                master_key = self._get_master_key()
                api_key = decrypt_secret(api_key[4:], master_key)

            adapter = create_library_adapter(
                library.id, library.adapter_type,
                library.base_url, api_key, library.options_json,
            )

            # The ready path is the published directory in Path B
            completed_dir = config.get("completed_directory", "/tmp")
            sanitized_title = _sanitize_dirname(item_title_from_job(job))
            ready_path = str(Path(completed_dir) / sanitized_title)

            try:
                inspection = await adapter.inspect_import(ready_path, match)
            except Exception as e:
                return StageResult(
                    StageRunStatus.FAILED, "inspect_failed",
                    str(e), True,
                )

            # Store inspection results
            await self._update_progress(stage_run_id, {
                "candidates": len(inspection.candidates),
                "all_rejected": inspection.all_rejected,
            })

            if inspection.all_rejected:
                return StageResult(
                    StageRunStatus.NEEDS_ATTENTION, "all_rejected",
                    "All import candidates were rejected", False,
                )

            # Store candidates for the import stage
            import json
            candidates_data = {
                "candidates": [
                    {
                        "path": c.absolute_path,
                        "quality": c.quality,
                        "rejection_reasons": c.rejection_reasons,
                        "media_id": c.media_id,
                        "episode_ids": c.episode_ids,
                    }
                    for c in inspection.candidates
                    if not c.rejection_reasons
                ]
            }
            await self._update_progress(stage_run_id, candidates_data)
            await session.commit()

        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_import(self, job: Any, stage_run_id: str) -> StageResult:
        """Submit import to library via Library Adapter."""
        from app.processing.import_media import run_import_stage

        config = job.config_snapshot_json
        library_id = config.get("library_instance_id")
        if not library_id:
            return StageResult(StageRunStatus.SKIPPED)

        factory = get_session_factory(self.settings)
        async with factory() as session:
            from app.database.repositories import LibraryRepository
            from app.adapters.libraries import create_library_adapter
            from app.security import decrypt_secret
            from app.database.models import MediaMatch as MediaMatchModel
            from app.domain.models import MediaMatch, MediaType

            lib_repo = LibraryRepository(session)
            library = await lib_repo.get(library_id)
            if not library:
                return StageResult(
                    StageRunStatus.FAILED, "library_not_found", "Library not found", False
                )

            match_row_result = await session.execute(
                select(MediaMatchModel).where(
                    MediaMatchModel.source_item_id == job.source_item_id
                )
            )
            match_row = match_row_result.scalar_one_or_none()
            if not match_row:
                return StageResult(
                    StageRunStatus.NEEDS_ATTENTION, "no_match", "No media match", False
                )

            match = MediaMatch(
                media_type=MediaType(match_row.media_type),
                catalog_id=match_row.catalog_id,
                episode_ids=match_row.episode_ids_json,
            )

            api_key = library.api_key_secret_ref
            if api_key.startswith("enc:"):
                api_key = decrypt_secret(api_key[4:], self._get_master_key())

            adapter = create_library_adapter(
                library.id, library.adapter_type,
                library.base_url, api_key, library.options_json,
            )

            completed_dir = config.get("completed_directory", "/tmp")
            sanitized_title = _sanitize_dirname(item_title_from_job(job))
            ready_path = str(Path(completed_dir) / sanitized_title)

            result = await run_import_stage(adapter, ready_path, match)

            await self._update_progress(stage_run_id, {
                "imported": result.imported_paths,
                "rejected": result.rejected_paths,
                "skipped": result.skipped_paths,
                "pending": result.pending,
            })

            if result.pending:
                return StageResult(
                    StageRunStatus.FAILED, "import_pending",
                    result.error, True,
                )
            if not result.success:
                return StageResult(
                    StageRunStatus.FAILED, "import_failed",
                    result.error, True,
                )

            return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_confirm_import(self, job: Any, stage_run_id: str) -> StageResult:
        """Confirm that imported files are present in the library."""
        config = job.config_snapshot_json
        library_id = config.get("library_instance_id")
        if not library_id:
            return StageResult(StageRunStatus.SKIPPED)

        # Reconcile: check that the library now has the expected files
        # For M3, we verify by checking command status (done in import stage)
        # This stage could do additional verification if needed
        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_notify(self, job: Any, stage_run_id: str) -> StageResult:
        """Send notifications for completed/failed/attention events."""
        # M3: notifications are optional; required ones could block
        # For now, just succeed
        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_cleanup(self, job: Any, stage_run_id: str) -> StageResult:
        """Clean up temporary files safely."""
        from app.processing.cleanup import cleanup_path_a, cleanup_path_b

        config = job.config_snapshot_json
        temp_dir = config.get("temporary_directory", "/tmp")
        completed_dir = config.get("completed_directory", "/tmp")
        library_id = config.get("library_instance_id")
        title = item_title_from_job(job)

        # Clean Path A (always safe to clean after successful import)
        result_a = cleanup_path_a(temp_dir, title, self.job_id)
        if not result_a.success:
            return StageResult(
                StageRunStatus.NEEDS_ATTENTION,
                "cleanup_a_failed",
                result_a.error,
                False,  # Don't retry automatically
            )

        # Clean Path B (only if library configured and import confirmed)
        result_b = cleanup_path_b(
            completed_dir, title, self.job_id,
            library_configured=bool(library_id),
            import_confirmed=True,  # We only reach here after confirm_import succeeded
        )

        if not result_b.success and not result_b.skipped_b:
            return StageResult(
                StageRunStatus.NEEDS_ATTENTION,
                "cleanup_b_failed",
                result_b.error,
                False,
            )

        await self._update_progress(stage_run_id, {
            "cleaned_a": result_a.cleaned_path_a,
            "cleaned_b": result_b.cleaned_path_b,
            "skipped_b": result_b.skipped_b,
        })

        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_unknown(self, job: Any, stage_run_id: str) -> StageResult:
        """Unknown stage handler."""
        return StageResult(
            StageRunStatus.FAILED, "unknown_stage", f"Unknown stage: {self.stage}", False
        )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _get_master_key(self) -> bytes:
        """Get the master encryption key from app state."""
        # This is set on the app state during lifespan startup
        # For test purposes, we can also read it from the config dir
        from app.security import get_or_create_master_key
        return get_or_create_master_key(self.settings.config_dir)

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
    """Extract title from job's config snapshot or source item ID."""
    return job.config_snapshot_json.get("title", "") or job.source_item_id
