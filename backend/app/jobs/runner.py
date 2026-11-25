"""Job runner — executes a single job stage.

Each stage implementation is idempotent and reconcileable.
Stages run outside the DB transaction; progress is persisted periodically.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from app.database.repositories import JobRepository
from app.database.session import get_session_factory
from app.domain.models import EligibilityStatus, JobStage, StageRunStatus, TransferStatus
from app.logging_buffer import job_name
from app.processing.publication import long_path, plain_path
from app.security import decrypt_secret
from app.settings import Settings

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class StageResult:
    """Result of running a single stage."""

    status: StageRunStatus
    error_code: str = ""
    error_detail: str = ""
    retryable: bool = True
    progress: dict[str, Any] | None = None


# Library verdicts that stop the job at check_library: (error_code, detail). The scheduler
# turns the first two into a waiting status / skipped (see scheduler._PARKED).
_LIBRARY_VERDICTS = {
    EligibilityStatus.NOT_REGISTERED.value: ("not_registered", "Not in library yet"),
    EligibilityStatus.ALREADY_AVAILABLE.value: ("already_available", "Already in library"),
    EligibilityStatus.NEEDS_REVIEW.value: ("needs_review", "Library needs review"),
}


def _import_match(match_row: Any, job: Any, library: Any) -> Any:
    """What the import expects the files to be. With the library check skipped (a pack the
    library can't parse as one title) the library matches each file on its own instead."""
    from app.domain.models import MediaMatch, MediaType

    if job.config_snapshot_json.get("skip_library"):
        return MediaMatch(
            media_type=MediaType.MOVIE if library.adapter_type == "radarr" else MediaType.SERIES
        )
    if match_row:
        return MediaMatch(
            media_type=MediaType(match_row.media_type),
            catalog_id=match_row.catalog_id,
            episode_ids=match_row.episode_ids_json,
        )
    return None


class JobRunner:
    """Runs a single job stage."""

    def __init__(self, settings: Settings, job_id: str, stage: str, worker_token: str) -> None:
        self.settings = settings
        self.job_id = job_id
        self.stage = stage
        self.worker_token = worker_token
        self._heartbeat_task: asyncio.Task | None = None
        self._cancelled = False
        self.label = job_id  # "Title" (id) once the job is loaded, for log lines

    async def execute(self) -> StageResult:
        """Execute the stage and return the result."""
        factory = get_session_factory(self.settings)

        # Create stage_run record
        async with factory() as session:
            repo = JobRepository(session)
            job = await repo.get(self.job_id)
            if not job:
                return StageResult(StageRunStatus.FAILED, "job_not_found", "Job not found", False)
            self.label = job_name(job)

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
            await self._close_run(
                stage_run.id, result.status.value, result.error_code, result.error_detail
            )
            return result
        except asyncio.CancelledError:
            await self._close_run(stage_run.id, "cancelled", "cancelled", "Stage cancelled")
            raise
        except Exception as exc:
            await self._close_run(
                stage_run.id, StageRunStatus.FAILED.value, "unexpected_error", repr(exc)
            )
            raise
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
        while True:
            await asyncio.sleep(interval)
            try:
                await self._renew_lease()
            except Exception:
                logger.warning("Heartbeat failed for job %s", self.label, exc_info=True)

    async def _renew_lease(self) -> None:
        async with get_session_factory(self.settings)() as session:
            repo = JobRepository(session)
            job = await repo.get(self.job_id)
            if job and job.worker_token == self.worker_token:
                await repo.update(
                    self.job_id,
                    lease_expires_at=_utcnow()
                    + timedelta(seconds=self.settings.stage_lease_seconds),
                )
                await session.commit()

    def _get_stage_handler(self) -> Any:
        """Return the handler function for the current stage."""
        handlers = {
            JobStage.CHECK_LIBRARY.value: self._stage_check_library,
            JobStage.TRANSFER.value: self._stage_transfer,
            JobStage.VERIFY.value: self._stage_verify,
            JobStage.EXTRACT.value: self._stage_extract,
            JobStage.MOVE.value: self._stage_move,
            JobStage.INSPECT_IMPORT.value: self._stage_inspect_import,
            JobStage.IMPORT.value: self._stage_import,
            JobStage.CLEANUP.value: self._stage_cleanup,
        }
        return handlers.get(self.stage, self._stage_unknown)

    # -----------------------------------------------------------------------
    # Stage implementations
    # -----------------------------------------------------------------------

    async def _files_not_visible(
        self, transfer: Any, endpoint: Any, item: Any, manifest: list
    ) -> str | None:
        """Why the manifest's files can't all be seen on the endpoint yet, or None when they can."""
        from app.adapters.transfers import create_transfer_adapter
        from app.domain.models import SourceItemDTO, SourceStatus

        adapter = create_transfer_adapter(
            transfer.id, transfer.adapter_type, self._transfer_config(transfer, endpoint)
        )
        source_item = SourceItemDTO(
            remote_id=item.remote_id,
            name=item.title,
            labels=item.labels_json,
            status=SourceStatus.COMPLETED,
            remote_base_path=item.remote_path,
        )
        try:
            remote = await adapter.inspect(
                source_item, manifest, path_mappings=endpoint.path_mappings_json
            )
        except Exception as exc:
            return f"Files not yet visible on transfer endpoint: {exc}"
        missing = len(manifest) - len(remote.files)
        if missing > 0:
            return f"{missing} of {len(manifest)} files not yet visible on transfer endpoint"
        return None

    async def _live_transfer_id(self, job: Any) -> str | None:
        from app.database.models import SourceInstance, SourceLabelRule

        async with get_session_factory(self.settings)() as session:
            rule = await session.get(SourceLabelRule, job.rule_id) if job.rule_id else None
            if rule and rule.transfer_override_id:
                return rule.transfer_override_id
            source_id = job.config_snapshot_json.get("source_id")
            source = await session.get(SourceInstance, source_id) if source_id else None
            return source.default_transfer_id if source else None

    async def _stage_check_library(self, job: Any, stage_run_id: str) -> StageResult:
        """Ask the library (fresh, no cached verdict) whether this release is wanted, then gate on the rule."""
        from app.database.models import LibraryInstance, SourceItem, SourceLabelRule
        from app.services import classification

        if job.config_snapshot_json.get("skip_library"):
            await self._update_progress(stage_run_id, {"eligibility": "skipped_by_user"})
            return StageResult(StageRunStatus.SUCCEEDED)

        async with get_session_factory(self.settings)() as session:
            item = await session.get(SourceItem, job.source_item_id)
            rule = await session.get(SourceLabelRule, job.rule_id)
            if not item or not rule:
                return StageResult(
                    StageRunStatus.FAILED,
                    "item_not_found",
                    "Source item or tag rule not found",
                    False,
                )
            library = (
                await session.get(LibraryInstance, rule.library_instance_id)
                if rule.library_instance_id
                else None
            )
            eligibility = await classification.classify_item(
                session, item, rule, library, self._get_master_key()
            )
            automatic = rule.automatic_processing
            summary = await _library_summary(session, item, library)
            await session.commit()

        await self._update_progress(stage_run_id, {"eligibility": eligibility, **summary})
        if eligibility == EligibilityStatus.WAITING_LIBRARY.value:
            return StageResult(
                StageRunStatus.FAILED, "library_unreachable", "Library unreachable", True
            )
        parked = _LIBRARY_VERDICTS.get(eligibility)
        if parked:
            return StageResult(StageRunStatus.NEEDS_ATTENTION, *parked, False)
        if not automatic and not job.config_snapshot_json.get("approved"):
            return StageResult(
                StageRunStatus.NEEDS_ATTENTION,
                "awaiting_approval",
                "Waiting for you to start it",
                False,
            )
        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_transfer(self, job: Any, stage_run_id: str) -> StageResult:
        """Transfer files from the remote endpoint to Path A."""
        config = job.config_snapshot_json
        transfer_id = config.get("transfer_id")
        temp_dir = config.get("temporary_directory", "/tmp")
        if not transfer_id:
            # Snapshot may predate the fetch config; resolve it live like discovery does
            transfer_id = await self._live_transfer_id(job)
        if not transfer_id:
            # Scheduler parks this as waiting_transfer until fetch is configured
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

            # Get source instance for adapter config
            from app.database.repositories import SourceRepository
            from app.security import decrypt_secret

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
                    logger.warning("Could not decrypt source credentials")
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
            source_adapter = create_source_adapter(source.id, source.adapter_type, source_config)

            # Get file manifest from source adapter
            try:
                manifest = await source_adapter.get_manifest(item.remote_id)
            except Exception as exc:
                logger.error("Failed to get file manifest: %s", exc)
                return StageResult(StageRunStatus.FAILED, "manifest_error", str(exc), True)

            if not manifest:
                return StageResult(
                    StageRunStatus.NEEDS_ATTENTION,
                    "no_files",
                    "No completed files found in source manifest",
                    True,
                )

            # Seedbox done doesn't mean the files are reachable yet (e.g. a mover still
            # copying them); wait and retry rather than failing transfers one by one.
            if endpoints:
                waiting = await self._files_not_visible(transfer, endpoints[0], item, manifest)
                if waiting:
                    return StageResult(StageRunStatus.FAILED, "waiting_for_source", waiting, True)

            # One job_files row per manifest file up front, so every expected file shows
            # (pending) before its transfer starts. Rows from earlier attempts are reused.
            job_repo = JobRepository(session)
            from app.database.models import JobFile

            rows = {
                f.remote_relpath: f
                for f in (
                    await session.execute(select(JobFile).where(JobFile.job_id == self.job_id))
                ).scalars()
            }
            for file_dto in manifest:
                row = rows.get(file_dto.relative_path)
                if row is None:
                    row = JobFile(job_id=self.job_id, remote_relpath=file_dto.relative_path)
                    session.add(row)
                    rows[file_dto.relative_path] = row
                if row.transfer_status != TransferStatus.COMPLETED.value:
                    row.transfer_status = TransferStatus.PENDING.value
                    row.bytes_received = 0
                row.size_bytes = file_dto.size_bytes
            await session.flush()
            existing_files = {rel: row.id for rel, row in rows.items()}

            total_bytes = sum(f.size_bytes for f in manifest)
            await job_repo.update(self.job_id, download_bytes_total=total_bytes)
            await session.commit()

        # Download each file
        # Use the transfer adapter to download files to Path A
        # Mirror the remote item: a single-file torrent is just that file in the
        # in-progress folder, a multi-file one is its folder.
        local_base = Path(temp_dir) / _sanitize_dirname(item.title)
        single = len(manifest) == 1 and manifest[0].relative_path == item.title

        bytes_done = 0
        for file_dto in manifest:
            if self._cancelled:
                return StageResult(StageRunStatus.FAILED, "cancelled", "Download cancelled", False)

            local_path = local_base if single else local_base / file_dto.relative_path
            local_rel = local_path.relative_to(temp_dir).as_posix()
            local_path = long_path(local_path)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            part_path = str(local_path) + ".part"

            # Finished by an earlier attempt (e.g. one that crashed afterwards): don't fetch again.
            if local_path.exists() and local_path.stat().st_size == file_dto.size_bytes:
                logger.info("Already downloaded: %s", file_dto.relative_path)
                bytes_done = await self._record_file(
                    file_dto, local_rel, existing_files, bytes_done, total_bytes, stage_run_id
                )
                continue

            # Check for existing .part file for resume
            resume_offset = 0
            if os.path.exists(part_path):
                resume_offset = os.path.getsize(part_path)
                logger.info("Resuming %s from offset %d", file_dto.relative_path, resume_offset)

            # Build transfer config from first available endpoint
            if not endpoints:
                return StageResult(
                    StageRunStatus.FAILED, "no_endpoints", "No transfer endpoints configured", False
                )

            endpoint = endpoints[0]  # For now, use first endpoint

            transfer_config = self._transfer_config(transfer, endpoint)

            from app.adapters.transfers import create_transfer_adapter

            transfer_adapter = create_transfer_adapter(
                transfer_id, transfer.adapter_type, transfer_config
            )

            # The callback runs in the transfer thread: only stash the count there,
            # and let a flusher task write it to the job row every couple of seconds.
            received_now = resume_offset
            file_id = existing_files[file_dto.relative_path]
            await self._set_file(
                file_id,
                transfer_status=TransferStatus.IN_PROGRESS.value,
                bytes_received=resume_offset,
            )

            def progress_cb(received: int, total: int) -> None:
                nonlocal received_now
                received_now = received

            async def flush_progress(base: int) -> None:
                last = -1
                while True:
                    await asyncio.sleep(2)
                    # Late binding is intended: progress_cb updates received_now and the
                    # flusher is cancelled before the loop moves on.
                    if received_now != last:  # noqa: B023
                        last = received_now  # noqa: B023
                        try:
                            await self._set_download_bytes(base + last, file_id, last)  # noqa: B023
                        except Exception as exc:  # progress is cosmetic; never kill the flusher
                            logger.debug("Progress flush failed: %s", exc)

            flusher = asyncio.create_task(flush_progress(bytes_done))
            try:
                result = await transfer_adapter.transfer_file(
                    remote_file=file_dto,
                    remote_base_path=item.remote_path,
                    destination_part_path=part_path,
                    resume_offset=resume_offset,
                    progress_callback=progress_cb,
                    path_mappings=endpoint.path_mappings_json if endpoint else None,
                )
            except Exception:
                await self._set_file(file_id, transfer_status=TransferStatus.FAILED.value)
                raise
            finally:
                flusher.cancel()

            if not result.success:
                await self._set_file(file_id, transfer_status=TransferStatus.FAILED.value)
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
                        file_dto.relative_path,
                        file_dto.size_bytes,
                        actual_size,
                    )
                    await self._set_file(file_id, transfer_status=TransferStatus.FAILED.value)
                    return StageResult(
                        StageRunStatus.FAILED,
                        "size_mismatch",
                        f"File {file_dto.relative_path} size mismatch",
                        True,
                    )

                # Atomic .part → final; replace (not rename) so a stale final file can't block it on Windows
                os.replace(part_path, str(local_path))

            bytes_done = await self._record_file(
                file_dto, local_rel, existing_files, bytes_done, total_bytes, stage_run_id
            )

        return StageResult(StageRunStatus.SUCCEEDED)

    async def _record_file(
        self,
        file_dto: Any,
        local_rel: str,
        existing_files: dict,
        bytes_done: int,
        total_bytes: int,
        stage_run_id: str,
    ) -> int:
        """Mark a file downloaded (one row per file across retries); returns the new bytes_done."""
        from app.database.models import JobFile

        bytes_done += file_dto.size_bytes
        async with get_session_factory(self.settings)() as session:
            prev_id = existing_files.get(file_dto.relative_path)
            job_file = await session.get(JobFile, prev_id) if prev_id else None
            if job_file is None:
                job_file = JobFile(job_id=self.job_id, remote_relpath=file_dto.relative_path)
                session.add(job_file)
            job_file.size_bytes = file_dto.size_bytes
            job_file.local_relpath = local_rel  # relative to the in-progress folder
            job_file.bytes_received = file_dto.size_bytes
            job_file.transfer_status = TransferStatus.COMPLETED.value
            job_file.verified_at = _utcnow()
            await JobRepository(session).update(self.job_id, download_bytes_done=bytes_done)
            await session.commit()
        # Separate session after commit: a second writer inside the first one locks SQLite.
        await self._update_progress(
            stage_run_id,
            {
                "file": file_dto.relative_path,
                "bytes_done": bytes_done,
                "bytes_total": total_bytes,
            },
        )
        return bytes_done

    async def _stage_verify(self, job: Any, stage_run_id: str) -> StageResult:
        """Verify transferred files (SFV CRC32 check, size check)."""
        from app.processing.verification import find_sfv_files, parse_sfv, verify_files

        item = long_path(_item_path(job))
        if not item.exists():
            return StageResult(
                StageRunStatus.NEEDS_ATTENTION,
                "no_files",
                f"Downloaded item not found: {plain_path(item)}",
                False,
            )

        # Find SFV files
        sfv_files = find_sfv_files(item) if item.is_dir() else []
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

        # Show what's being checked while it runs: CRC32 of a big pack takes minutes.
        await self._update_progress(
            stage_run_id,
            {
                "files": [{"path": f["remote_relpath"], "result": "checking"} for f in job_files],
            },
        )
        # Off the event loop: CRC32 reads every byte and would stall heartbeats.
        result = await asyncio.to_thread(
            verify_files,
            item.parent,
            job_files,
            sfv_entries if sfv_entries else None,
        )

        outcome = {p: ("crc32 ok", "") for p in result.verified}
        outcome |= {p: ("size ok", "") for p in result.size_only}
        outcome |= {p: ("failed", why) for p, why in result.failed}
        outcome |= {p: ("missing", "") for p in result.missing}
        await self._update_progress(
            stage_run_id,
            {
                "checks": result.checks_performed,
                "files": [{"path": p, "result": r, "detail": d} for p, (r, d) in outcome.items()],
            },
        )

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

        local_dir = long_path(_item_path(job))
        if not local_dir.exists():
            return StageResult(
                StageRunStatus.FAILED,
                "no_files",
                f"Downloaded item not found: {plain_path(local_dir)}",
                False,
            )
        if local_dir.is_file():
            return StageResult(StageRunStatus.SKIPPED)

        archives = detect_archives(local_dir)
        if not archives:
            return StageResult(StageRunStatus.SKIPPED)

        # Progress = bytes of new files vs the downloaded size.
        # ponytail: assumes output ~ input (scene RARs are stored, not compressed); clamped to total.
        before = {f for f in local_dir.rglob("*") if f.is_file()}
        total = sum(f.stat().st_size for f in before) or 1

        def written() -> int:
            n = 0
            for f in local_dir.rglob("*"):
                if f not in before:
                    try:
                        n += f.stat().st_size if f.is_file() else 0
                    except OSError:  # file renamed or removed by the extractor mid-scan
                        pass
            return min(n, total)

        # Per archive (first volume only): what came out of it. files is None while unpacking.
        unpacked: list[dict[str, Any]] = []

        def rel(f: Path) -> str:
            return f.relative_to(local_dir).as_posix()

        async def flush_progress() -> None:
            while True:
                await asyncio.sleep(2)
                try:
                    done = await asyncio.to_thread(written)
                    await self._update_progress(
                        stage_run_id,
                        {"bytes_done": done, "bytes_total": total, "archives": unpacked},
                    )
                except Exception as exc:  # progress is cosmetic; never kill the flusher
                    logger.debug("Extract progress flush failed: %s", exc)

        flusher = asyncio.create_task(flush_progress())
        done: set[Path] = set()
        seen = set(before)
        try:
            # Rounds: an archive can hold archives (subs .rar holding a vobsub .sub .rar).
            for _ in range(3):  # ponytail: 3 levels of nesting; scene releases use 2
                for archive in archives:
                    done.add(archive)
                    entry: dict[str, Any] = {"archive": rel(archive), "files": None}
                    unpacked.append(entry)
                    # Next to the archive, in place: a pack of releases keeps one folder per
                    # release, and publish moves only the files that weren't downloaded.
                    # Off the event loop: unrar can run for minutes and would stall heartbeats.
                    result = await asyncio.to_thread(extract_archive, archive, archive.parent)
                    if not result.success:
                        await self._update_progress(stage_run_id, {"archives": unpacked})
                        return StageResult(
                            StageRunStatus.NEEDS_ATTENTION,
                            "extraction_failed",
                            f"{archive.name}: {result.error}",
                            not result.success,  # Some extraction errors are retryable
                        )
                    new = {f for f in local_dir.rglob("*") if f.is_file()} - seen
                    seen |= new
                    entry["files"] = sorted(rel(f) for f in new)
                archives = [a for a in detect_archives(local_dir) if a not in done]
                if not archives:
                    break
        finally:
            flusher.cancel()

        await self._update_progress(
            stage_run_id,
            {
                "bytes_done": total,
                "bytes_total": total,
                "archives": unpacked,
            },
        )
        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_move(self, job: Any, stage_run_id: str) -> StageResult:
        """Move the downloaded item (or, for archives, the extracted files) to the completed folder."""
        from app.processing.publication import publish_item

        result = publish_item(
            _item_path(job),
            job.config_snapshot_json.get("completed_directory", "/tmp"),
            downloaded={f.local_relpath or f.remote_relpath for f in job.job_files},
        )

        await self._update_progress(
            stage_run_id,
            {
                "published_path": result.published_path,
                "files": result.published_files,
            },
        )

        if not result.success:
            return StageResult(
                StageRunStatus.FAILED,
                "publish_failed",
                result.error,
                True,
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
            from app.adapters.libraries import create_library_adapter
            from app.database.models import MediaMatch as MediaMatchModel
            from app.database.repositories import LibraryRepository
            from app.security import decrypt_secret

            lib_repo = LibraryRepository(session)
            library = await lib_repo.get(library_id)
            if not library:
                return StageResult(
                    StageRunStatus.FAILED,
                    "library_not_found",
                    "Library instance not found",
                    False,
                )

            # Get the media match for this source item
            match_result = await session.execute(
                select(MediaMatchModel).where(MediaMatchModel.source_item_id == job.source_item_id)
            )
            match = _import_match(match_result.scalar_one_or_none(), job, library)
            if not match:
                return StageResult(
                    StageRunStatus.NEEDS_ATTENTION,
                    "no_match",
                    "No media match found for source item",
                    False,
                )

            # Decrypt API key
            api_key = library.api_key_secret_ref
            if api_key.startswith("enc:"):
                master_key = self._get_master_key()
                api_key = decrypt_secret(api_key[4:], master_key)

            adapter = create_library_adapter(
                library.id,
                library.adapter_type,
                library.base_url,
                api_key,
                library.options_json,
            )

            # The ready path is the published directory in Path B
            completed_dir = config.get("completed_directory", "/tmp")
            sanitized_title = _sanitize_dirname(item_title_from_job(job))
            ready_path = _library_path(
                str(Path(completed_dir) / sanitized_title),
                (library.options_json or {}).get("path_mappings"),
            )

            try:
                inspection = await adapter.inspect_import(ready_path, match)
            except Exception as e:
                return StageResult(
                    StageRunStatus.FAILED,
                    "inspect_failed",
                    str(e),
                    True,
                )

            # Store inspection results
            await self._update_progress(
                stage_run_id,
                {
                    "candidates": len(inspection.candidates),
                    "all_rejected": inspection.all_rejected,
                },
            )

            if inspection.all_rejected:
                return StageResult(
                    StageRunStatus.NEEDS_ATTENTION,
                    "all_rejected",
                    _rejection_summary(inspection, ready_path),
                    False,
                )

            # Store candidates for the import stage

            candidates_data = {
                "candidates": [
                    {
                        "path": c.absolute_path,
                        "quality": c.quality,
                        "rejection_reasons": c.rejection_reasons,
                        "media_id": c.media_id,
                        "episode_ids": c.episode_ids,
                    }
                    for c in inspection.candidates  # rejected too: their reasons are the record
                ]
            }
            await self._update_progress(stage_run_id, candidates_data)
            await session.commit()

        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_import(self, job: Any, stage_run_id: str) -> StageResult:
        """Submit import to library via Library Adapter."""
        from app.database.models import SourceItem
        from app.processing.import_media import run_import_stage

        config = job.config_snapshot_json
        library_id = config.get("library_instance_id")
        if not library_id:
            return StageResult(StageRunStatus.SKIPPED)

        factory = get_session_factory(self.settings)
        async with factory() as session:
            from app.adapters.libraries import create_library_adapter
            from app.database.models import MediaMatch as MediaMatchModel
            from app.database.repositories import LibraryRepository
            from app.security import decrypt_secret

            lib_repo = LibraryRepository(session)
            library = await lib_repo.get(library_id)
            if not library:
                return StageResult(
                    StageRunStatus.FAILED, "library_not_found", "Library not found", False
                )

            match_row_result = await session.execute(
                select(MediaMatchModel).where(MediaMatchModel.source_item_id == job.source_item_id)
            )
            match = _import_match(match_row_result.scalar_one_or_none(), job, library)
            if not match:
                return StageResult(
                    StageRunStatus.NEEDS_ATTENTION, "no_match", "No media match", False
                )

            api_key = library.api_key_secret_ref
            if api_key.startswith("enc:"):
                api_key = decrypt_secret(api_key[4:], self._get_master_key())

            adapter = create_library_adapter(
                library.id,
                library.adapter_type,
                library.base_url,
                api_key,
                library.options_json,
            )

            completed_dir = config.get("completed_directory", "/tmp")
            sanitized_title = _sanitize_dirname(item_title_from_job(job))
            ready_path = _library_path(
                str(Path(completed_dir) / sanitized_title),
                (library.options_json or {}).get("path_mappings"),
            )

            # Use the stored torrent identity, never a title/path guess. Arr tracks
            # torrent download IDs in uppercase; manual imports otherwise lose the link.
            item = await session.get(SourceItem, job.source_item_id)
            download_id = item.infohash.upper() if item and item.infohash else None
            result = await run_import_stage(adapter, ready_path, match, download_id=download_id)

            await self._update_progress(
                stage_run_id,
                {
                    "imported": result.imported_paths,
                    "rejected": result.rejected_paths,
                    "skipped": result.skipped_paths,
                    "pending": result.pending,
                },
            )

            if result.pending:
                return StageResult(
                    StageRunStatus.FAILED,
                    "import_pending",
                    result.error,
                    True,
                )
            if result.partial:
                # Not retryable: a re-inspect would see only the rejected files.
                return StageResult(
                    StageRunStatus.NEEDS_ATTENTION,
                    "import_partial",
                    result.error,
                    False,
                )
            if not result.success:
                return StageResult(
                    StageRunStatus.FAILED,
                    "import_failed",
                    result.error,
                    True,
                )

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
            completed_dir,
            title,
            self.job_id,
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

        # In progress (A): the downloaded archives, so a count is enough. Completed (B):
        # what the library left behind, which is worth seeing file by file.
        await self._update_progress(
            stage_run_id,
            {
                "cleaned_a": plain_path(result_a.cleaned_path_a),
                "deleted_a": {"count": len(result_a.deleted), "bytes": result_a.deleted_bytes},
                "cleaned_b": plain_path(result_b.cleaned_path_b),
                "deleted_b": {"files": result_b.deleted, "bytes": result_b.deleted_bytes},
                "skipped_b": result_b.skipped_b,
            },
        )

        return StageResult(StageRunStatus.SUCCEEDED)

    async def _stage_unknown(self, job: Any, stage_run_id: str) -> StageResult:
        """Unknown stage handler."""
        return StageResult(
            StageRunStatus.FAILED, "unknown_stage", f"Unknown stage: {self.stage}", False
        )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _transfer_config(self, transfer: Any, endpoint: Any) -> dict[str, Any]:
        """Adapter config for an endpoint: transfer settings + host/port + decrypted credentials."""
        config = {**transfer.config_json, "host": endpoint.host, "port": endpoint.port}
        cred_ref = endpoint.credential_ref
        if isinstance(cred_ref, str) and cred_ref.startswith("enc:"):
            try:
                config.update(json.loads(decrypt_secret(cred_ref[4:], self._get_master_key())))
            except Exception:
                logger.warning("Could not decrypt credentials for endpoint %s", endpoint.host)
        return config

    def _get_master_key(self) -> bytes:
        """Get the master encryption key from app state."""
        # This is set on the app state during lifespan startup
        # For test purposes, we can also read it from the config dir
        from app.security import get_or_create_master_key

        return get_or_create_master_key(self.settings.config_dir)

    async def _close_run(
        self, run_id: str, status: str, error_code: str, error_detail: str
    ) -> None:
        """Record a stage run's outcome; without this every attempt stays 'running' forever."""
        from sqlalchemy import update

        from app.database.models import StageRun

        async with get_session_factory(self.settings)() as session:
            await session.execute(
                update(StageRun)
                .where(StageRun.id == run_id)
                .values(
                    status=status,
                    ended_at=_utcnow(),
                    error_code=error_code or None,
                    error_detail=error_detail or None,
                )
            )
            await session.commit()

    async def _set_download_bytes(self, n: int, file_id: str, file_bytes: int) -> None:
        """Progress of the job and of the file being transferred, in one write."""
        from app.database.models import JobFile

        async with get_session_factory(self.settings)() as session:
            await JobRepository(session).update(self.job_id, download_bytes_done=n)
            await session.execute(
                update(JobFile).where(JobFile.id == file_id).values(bytes_received=file_bytes)
            )
            await session.commit()

    async def _set_file(self, file_id: str, **values: Any) -> None:
        from app.database.models import JobFile

        async with get_session_factory(self.settings)() as session:
            await session.execute(update(JobFile).where(JobFile.id == file_id).values(**values))
            await session.commit()

    async def _update_progress(self, stage_run_id: str, progress: dict[str, Any]) -> None:
        """Update stage_run progress in DB."""
        factory = get_session_factory(self.settings)
        async with factory() as session:
            from sqlalchemy import update

            from app.database.models import StageRun

            await session.execute(
                update(StageRun)
                .where(StageRun.id == stage_run_id)
                .values(progress_json=progress)  # StageRun has no updated_at column
            )
            await session.commit()


async def _library_summary(session: Any, item: Any, library: Any) -> dict[str, Any]:
    """What the library said about this release, from the rows classification just wrote:
    the verdict's reason and evidence, and how the library parsed the name."""
    from app.database.models import EligibilityCheck
    from app.database.models import MediaMatch as MediaMatchModel

    check = (
        await session.execute(
            select(EligibilityCheck)
            .where(EligibilityCheck.source_item_id == item.id)
            .order_by(EligibilityCheck.checked_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    match = (
        await session.execute(
            select(MediaMatchModel)
            .where(MediaMatchModel.source_item_id == item.id)
            .order_by(MediaMatchModel.matched_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    out: dict[str, Any] = {
        "library": f"{library.name} ({library.adapter_type})" if library else None,
        "reason": check.reason if check else "",
        "evidence": check.evidence_json if check else {},
    }
    if match:
        p = match.parse_json or {}
        parsed = {
            # Radarr: movieTitles/year/edition; Sonarr: seriesTitle/seasonNumber/episodeNumbers.
            "title": ", ".join(p.get("movieTitles") or [])
            or p.get("movieTitle")
            or p.get("seriesTitle"),
            "year": p.get("year") or None,
            "season": p.get("seasonNumber"),
            "episodes": p.get("episodeNumbers") or None,
            "full_season": p.get("fullSeason") or None,
            "edition": p.get("edition") or None,
            "quality": ((p.get("quality") or {}).get("quality") or {}).get("name"),
            "group": p.get("releaseGroup"),
        }
        out["match"] = {
            "media_type": match.media_type,
            "catalog_id": match.catalog_id,
            "episode_ids": len(match.episode_ids_json or []),
            "confidence": match.confidence,
            "parsed": {k: v for k, v in parsed.items() if v not in (None, "", [])},
        }
    return out


def _rejection_summary(inspection: Any, ready_path: str) -> str:
    """Explain why nothing is importable, using the reasons the library gave per file."""
    if not inspection.candidates:
        return f"Library found no importable files at {ready_path}"
    reasons = "; ".join(
        f"{Path(c.absolute_path).name}: {', '.join(c.rejection_reasons)}"
        for c in inspection.candidates
    )
    return f"All import candidates were rejected: {reasons}"


def _sanitize_dirname(name: str) -> str:
    """Sanitize a release name for use as a directory name."""
    # Remove illegal characters for most filesystems
    sanitized = name.replace("/", "_").replace("\\", "_").replace(":", "_")
    sanitized = sanitized.replace("<", "_").replace(">", "_").replace("|", "_")
    sanitized = sanitized.replace("?", "").replace("*", "").replace('"', "_")
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip(". ")
    return sanitized[:200]  # Limit length


def _library_path(path: str, mappings: list[dict] | None) -> str:
    """Translate a local path into the path the library sees, e.g. Sonarr in a container:
    D:\\Temp\\downloads\\tv\\X.mkv -> /downloads/tv/X.mkv for {local_prefix: D:\\Temp\\downloads,
    library_prefix: /downloads}. Unmapped paths pass through unchanged."""
    norm = path.replace("\\", "/")
    for m in mappings or []:
        local = (m.get("local_prefix") or "").replace("\\", "/").rstrip("/")
        lib = (m.get("library_prefix") or "").rstrip("/")
        if not local:
            continue
        head, rest = norm[: len(local)], norm[len(local) :]
        if head.lower() == local.lower() and (not rest or rest.startswith("/")):
            if "/" not in lib:  # Windows-style library prefix: keep backslashes
                return lib + rest.replace("/", "\\")
            return lib + rest
    return path


def _item_path(job: Any) -> Path:
    """The item as downloaded into the in-progress folder: one file or one folder."""
    temp_dir = job.config_snapshot_json.get("temporary_directory", "/tmp")
    return Path(temp_dir) / _sanitize_dirname(item_title_from_job(job))


def item_title_from_job(job: Any) -> str:
    """Extract title from job's config snapshot or source item ID."""
    return job.config_snapshot_json.get("title", "") or job.source_item_id
