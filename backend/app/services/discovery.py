"""Discovery service — polls source adapters and upserts items into inventory.

For each enabled source:
1. Call source_adapter.list_items()
2. Upsert each item into source_items table
3. Find the highest-priority matching label rule
4. Classify the item (parse + library check)
5. If eligible and auto-processing enabled and not already queued:
   - After onboarding complete, auto-queue new eligible items
6. Mark the source's last_scan_at and transition onboarding state
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    LibraryInstance,
    SourceInstance,
    SourceItem,
    SourceLabelRule,
    Job,
)
from app.database.repositories import (
    JobRepository,
    LabelRuleRepository,
    SourceItemRepository,
    SourceRepository,
)
from app.database.session import get_session_factory
from app.domain.models import EligibilityStatus, JobStage, JobStatus, OnboardingState
from app.settings import Settings

logger = logging.getLogger(__name__)

# Statuses that allow auto-queueing after onboarding
_AUTO_QUEUE_STATUSES = {
    EligibilityStatus.MISSING.value,
    EligibilityStatus.PARTIALLY_MISSING.value,
    EligibilityStatus.DOWNLOAD_NEEDED.value,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DiscoveryService:
    """Polls all enabled sources and processes their items."""

    def __init__(self, settings: Settings, master_key: bytes) -> None:
        self.settings = settings
        self.master_key = master_key

    async def run_discovery_for_source(self, source_id: str) -> dict[str, int]:
        """Run one full discovery cycle for a source.

        Returns counts: discovered, new, classified, queued, errors.
        """
        counts = {"discovered": 0, "new": 0, "classified": 0, "queued": 0, "errors": 0}
        factory = get_session_factory(self.settings)

        # Load source config
        async with factory() as session:
            source_repo = SourceRepository(session)
            source = await source_repo.get(source_id)
            if not source or not source.enabled:
                return counts

            source_id_copy = source.id
            adapter_type = source.adapter_type
            onboarding_state = source.onboarding_state
            label_rules = list(source.label_rules)
            conn_config_raw = dict(source.connection_config_json or {})
            cred_ref = source.credential_ref or ""
            await session.commit()

        # Build adapter config: non-secret config + decrypted credential
        from app.security import decrypt_secret
        import json

        conn_config = dict(conn_config_raw)
        if cred_ref.startswith("enc:"):
            try:
                plaintext = decrypt_secret(cred_ref[4:], self.master_key)
                try:
                    creds = json.loads(plaintext)
                    if isinstance(creds, dict):
                        conn_config.update(creds)
                    else:
                        conn_config["password"] = plaintext
                except json.JSONDecodeError:
                    conn_config["password"] = plaintext
            except Exception:
                pass
        elif cred_ref:
            # Unencrypted legacy — merge JSON dict
            try:
                creds = json.loads(cred_ref)
                if isinstance(creds, dict):
                    conn_config.update(creds)
            except json.JSONDecodeError:
                conn_config["password"] = cred_ref

        # Create source adapter
        from app.adapters.sources import create_source_adapter
        try:
            adapter = create_source_adapter(source_id_copy, adapter_type, conn_config)
            conn_ok = await adapter.test_connection()
            if not conn_ok.get("ok"):
                logger.warning(
                    "Source %s connection failed: %s", source_id_copy, conn_ok.get("error")
                )
                counts["errors"] += 1
                return counts
        except Exception as exc:
            logger.warning("Source %s adapter error: %s", source_id_copy, exc)
            counts["errors"] += 1
            return counts

        # List all items from source
        try:
            items_dto = await adapter.list_items()
        except Exception as exc:
            logger.warning("Source %s list_items failed: %s", source_id_copy, exc)
            counts["errors"] += 1
            return counts

        counts["discovered"] = len(items_dto)

        # Determine if this is first scan (for onboarding tracking)
        is_first_scan = onboarding_state == OnboardingState.PENDING.value
        newly_seen_ids = set()

        # Process each item in its own short transaction
        for item_dto in items_dto:
            try:
                await self._process_item(
                    source_id_copy,
                    item_dto,
                    label_rules,
                    onboarding_state,
                    counts,
                )
                newly_seen_ids.add(item_dto.remote_id)
            except Exception as exc:
                logger.debug(
                    "Error processing item %s from %s: %s",
                    item_dto.remote_id, source_id_copy, exc,
                )
                counts["errors"] += 1

        # Update source scan timestamps and onboarding
        async with factory() as session:
            source_repo = SourceRepository(session)
            update_kwargs: dict[str, Any] = {"last_scan_at": _utcnow()}

            if is_first_scan and len(items_dto) > 0:
                # First scan done — transition to awaiting_review
                update_kwargs["onboarding_state"] = OnboardingState.AWAITING_REVIEW.value
                update_kwargs["initial_scan_at"] = _utcnow()
                logger.info(
                    "Source %s first scan complete (%d items) — awaiting admin review",
                    source_id_copy, len(items_dto),
                )
            elif is_first_scan:
                # First scan, no items
                update_kwargs["onboarding_state"] = OnboardingState.AWAITING_REVIEW.value
                update_kwargs["initial_scan_at"] = _utcnow()

            await source_repo.update(source_id_copy, **update_kwargs)
            await session.commit()

        logger.info(
            "Source %s scan: discovered=%d new=%d classified=%d queued=%d errors=%d",
            source_id_copy, counts["discovered"], counts["new"],
            counts["classified"], counts["queued"], counts["errors"],
        )
        return counts

    async def _process_item(
        self,
        source_id: str,
        item_dto: Any,
        label_rules: list[SourceLabelRule],
        onboarding_state: str,
        counts: dict[str, int],
    ) -> None:
        factory = get_session_factory(self.settings)

        async with factory() as session:
            item_repo = SourceItemRepository(session)
            job_repo = JobRepository(session)

            # Upsert item
            item, created = await item_repo.upsert(
                source_id=source_id,
                remote_id=item_dto.remote_id,
                title=item_dto.name,
                labels_json=item_dto.labels,
                source_status=item_dto.status.value,
                remote_path=item_dto.remote_base_path,
                size_bytes=item_dto.total_bytes,
                completed_at=item_dto.completed_at,
                infohash=item_dto.infohash,
                remote_metadata_json=item_dto.metadata,
            )
            if created:
                counts["new"] += 1

            # Skip ignored items
            if item.ignored_at is not None:
                await session.commit()
                return

            # Find best matching label rule (highest priority, source-scoped)
            matched_rule = self._find_matching_rule(item_dto.labels, label_rules)

            if not matched_rule:
                # No rule → unrouted
                if item.last_eligibility != EligibilityStatus.UNROUTED.value:
                    await item_repo.update(
                        item.id, last_eligibility=EligibilityStatus.UNROUTED.value
                    )
                await session.commit()
                return

            # Load library if configured
            library: LibraryInstance | None = None
            if matched_rule.library_instance_id:
                result = await session.execute(
                    select(LibraryInstance).where(
                        LibraryInstance.id == matched_rule.library_instance_id
                    )
                )
                library = result.scalar_one_or_none()

            # Classify
            from app.services.classification import classify_item
            eligibility = await classify_item(
                session, item, matched_rule, library, self.master_key
            )
            counts["classified"] += 1

            # Auto-queue if eligible and onboarding completed
            should_auto_queue = (
                onboarding_state == OnboardingState.COMPLETED.value
                and matched_rule.automatic_processing
                and eligibility in _AUTO_QUEUE_STATUSES
                and item.ignored_at is None
            )

            if should_auto_queue:
                # Check no active job exists
                existing = await job_repo.get_active_for_item(item.id)
                if not existing:
                    await self._create_job(
                        session, item, matched_rule, source_id
                    )
                    counts["queued"] += 1

            await session.commit()

    def _find_matching_rule(
        self, labels: list[str], rules: list[SourceLabelRule]
    ) -> SourceLabelRule | None:
        """Find the highest-priority enabled rule that matches any of the item's labels."""
        if not labels or not rules:
            return None

        label_set = set(labels)
        candidates = [
            r for r in rules
            if r.enabled and r.label in label_set
        ]

        if not candidates:
            return None

        # Sort by priority descending; stable sort preserves order on ties
        candidates.sort(key=lambda r: r.priority, reverse=True)

        # If top priority is tied between rules with different labels, it's ambiguous
        # but since label is unique per source, ties should be rare; just pick first
        return candidates[0]

    async def _create_job(
        self,
        session: AsyncSession,
        item: SourceItem,
        rule: SourceLabelRule,
        source_id: str,
    ) -> Job:
        """Create a new job for an eligible item."""
        from app.database.repositories import SourceRepository

        source_repo = SourceRepository(session)
        source = await source_repo.get(source_id)

        transfer_id = rule.transfer_override_id or (source.default_transfer_id if source else None)

        config_snapshot = {
            "source_id": source_id,
            "source_name": source.name if source else "",
            "label": rule.label,
            "transfer_id": transfer_id,
            "library_instance_id": rule.library_instance_id,
            "temporary_directory": rule.temporary_directory,
            "completed_directory": rule.completed_directory,
            "retry_limit": self.settings.retry_limit,
            "stage_lease_seconds": self.settings.stage_lease_seconds,
            "title": item.title,
        }

        job_repo = JobRepository(session)
        job = await job_repo.create(
            source_item_id=item.id,
            rule_id=rule.id,
            config_snapshot_json=config_snapshot,
            priority=rule.priority,
            status=JobStatus.QUEUED.value,
            stage=JobStage.RESOLVE_SOURCE.value,
        )
        await job_repo.add_event(
            job_id=job.id,
            severity="info",
            kind="job.auto_queued",
            message=f"Auto-queued after discovery: eligibility={item.last_eligibility}",
            details_json={"eligibility": item.last_eligibility},
        )
        logger.info(
            "Auto-queued job %s for item %s (%s, label=%s)",
            job.id, item.id, item.title, rule.label,
        )
        return job
