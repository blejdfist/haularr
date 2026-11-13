"""Classification service — parse + inspect_library → eligibility decision.

For each source item with a matching label rule:
1. Find the library adapter instance (if any)
2. Call library.parse(title) → MediaMatch
3. If match found, call library.inspect_library(match) → LibraryInventory
4. Derive an EligibilityStatus from the inventory
5. Persist MediaMatch + EligibilityCheck in DB
6. Update source_item.last_eligibility
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.libraries import create_library_adapter
from app.database.models import SourceItem, SourceLabelRule, LibraryInstance
from app.database.repositories import SourceItemRepository
from app.domain.models import (
    EligibilityStatus,
    MediaMatch,
    MediaType,
)
from app.security import decrypt_secret

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def classify_item(
    session: AsyncSession,
    item: SourceItem,
    rule: SourceLabelRule,
    library: LibraryInstance | None,
    master_key: bytes,
) -> str:
    """Classify a source item and persist the result.

    Returns the EligibilityStatus string.
    """
    item_repo = SourceItemRepository(session)

    # Update status to classifying
    await item_repo.update(item.id, last_eligibility=EligibilityStatus.CLASSIFYING.value)
    await session.flush()

    # If source not completed, mark and exit
    if item.source_status not in ("completed", "stopped"):
        status = EligibilityStatus.WAITING_SOURCE_COMPLETION.value
        await _persist_check(session, item.id, rule.id, status, "Source not completed")
        await item_repo.update(item.id, last_eligibility=status, eligible_rule_id=rule.id)
        await session.flush()
        return status

    # No library adapter → download_needed
    if not library:
        status = EligibilityStatus.DOWNLOAD_NEEDED.value
        await _persist_check(session, item.id, rule.id, status, "No library configured")
        await item_repo.update(item.id, last_eligibility=status, eligible_rule_id=rule.id)
        await session.flush()
        return status

    # Build library adapter
    api_key = library.api_key_secret_ref
    if api_key.startswith("enc:"):
        try:
            api_key = decrypt_secret(api_key[4:], master_key)
        except Exception:
            status = EligibilityStatus.WAITING_LIBRARY.value
            await _persist_check(session, item.id, rule.id, status, "Could not decrypt API key")
            await item_repo.update(item.id, last_eligibility=status)
            await session.flush()
            return status

    try:
        adapter = create_library_adapter(
            library.id, library.adapter_type,
            library.base_url, api_key, library.options_json,
        )
    except Exception as exc:
        status = EligibilityStatus.WAITING_LIBRARY.value
        await _persist_check(session, item.id, rule.id, status, f"Adapter creation failed: {exc}")
        await item_repo.update(item.id, last_eligibility=status)
        await session.flush()
        return status

    # Test connection
    try:
        conn_result = await adapter.test_connection()
        if not conn_result.get("ok"):
            status = EligibilityStatus.WAITING_LIBRARY.value
            reason = conn_result.get("error", "Library unreachable")
            await _persist_check(session, item.id, rule.id, status, reason)
            await item_repo.update(item.id, last_eligibility=status)
            await session.flush()
            return status
    except Exception as exc:
        status = EligibilityStatus.WAITING_LIBRARY.value
        await _persist_check(session, item.id, rule.id, status, f"Connection failed: {exc}")
        await item_repo.update(item.id, last_eligibility=status)
        await session.flush()
        return status

    # Parse release name
    try:
        match = await adapter.parse(item.title)
    except Exception as exc:
        status = EligibilityStatus.NEEDS_REVIEW.value
        await _persist_check(session, item.id, rule.id, status, f"Parse failed: {exc}")
        await item_repo.update(item.id, last_eligibility=status)
        await session.flush()
        return status

    # Ambiguous parse → needs_review
    if match.ambiguous:
        status = EligibilityStatus.NEEDS_REVIEW.value
        await _persist_check(
            session, item.id, rule.id, status,
            "Ambiguous parse: multiple possible identities",
            evidence={"parse": match.parse_data},
        )
        await _persist_match(session, item.id, library.id, match)
        await item_repo.update(item.id, last_eligibility=status)
        await session.flush()
        return status

    # Not matched to a registered entity → not_registered
    if match.catalog_id is None:
        status = EligibilityStatus.NOT_REGISTERED.value
        await _persist_check(
            session, item.id, rule.id, status,
            f"Title not found in library: {item.title}",
            evidence={"parsed_title": match.title or item.title},
        )
        await _persist_match(session, item.id, library.id, match)
        await item_repo.update(item.id, last_eligibility=status)
        await session.flush()
        return status

    # Inspect library for file presence
    try:
        inventory = await adapter.inspect_library(match)
    except Exception as exc:
        status = EligibilityStatus.WAITING_LIBRARY.value
        await _persist_check(session, item.id, rule.id, status, f"Library inspect failed: {exc}")
        await item_repo.update(item.id, last_eligibility=status)
        await session.flush()
        return status

    if not inventory.registered:
        status = EligibilityStatus.NOT_REGISTERED.value
        await _persist_check(
            session, item.id, rule.id, status,
            "Catalog ID found in parse but not registered in library",
        )
        await _persist_match(session, item.id, library.id, match)
        await item_repo.update(item.id, last_eligibility=status)
        await session.flush()
        return status

    # Determine eligibility based on inventory
    if match.media_type == MediaType.MOVIE:
        if not inventory.has_file:
            status = EligibilityStatus.MISSING.value
        else:
            # Movie exists — check upgrade potential
            upgrade = await adapter.evaluate_candidate(match, {})
            from app.domain.models import EligibilityDecision
            if upgrade.decision == EligibilityDecision.ACCEPTED:
                status = EligibilityStatus.UPGRADE_ELIGIBLE.value
            elif upgrade.decision == EligibilityDecision.REJECTED:
                status = EligibilityStatus.ALREADY_AVAILABLE.value
            else:
                status = EligibilityStatus.UNCONFIRMED_UPGRADE.value
    else:
        # Series
        missing = inventory.missing_episode_ids
        if missing:
            if len(missing) < len(match.episode_ids) and match.episode_ids:
                status = EligibilityStatus.PARTIALLY_MISSING.value
            else:
                status = EligibilityStatus.MISSING.value
        else:
            upgrade = await adapter.evaluate_candidate(match, {})
            from app.domain.models import EligibilityDecision
            if upgrade.decision == EligibilityDecision.ACCEPTED:
                status = EligibilityStatus.UPGRADE_ELIGIBLE.value
            elif upgrade.decision == EligibilityDecision.REJECTED:
                status = EligibilityStatus.ALREADY_AVAILABLE.value
            else:
                status = EligibilityStatus.UNCONFIRMED_UPGRADE.value

    await _persist_match(session, item.id, library.id, match)
    await _persist_check(
        session, item.id, rule.id, status,
        f"Classification complete: {status}",
        evidence={
            "catalog_id": match.catalog_id,
            "missing_episode_ids": inventory.missing_episode_ids,
            "has_file": inventory.has_file,
        },
    )
    await item_repo.update(item.id, last_eligibility=status, eligible_rule_id=rule.id)
    await session.flush()
    return status


async def _persist_match(
    session: AsyncSession,
    source_item_id: str,
    library_instance_id: str,
    match: MediaMatch,
) -> None:
    item_repo = SourceItemRepository(session)
    await item_repo.save_media_match(
        source_item_id=source_item_id,
        library_instance_id=library_instance_id,
        media_type=match.media_type.value,
        catalog_id=match.catalog_id,
        episode_ids_json=match.episode_ids,
        parse_json=match.parse_data,
        confidence=match.confidence,
        ambiguous=match.ambiguous,
    )


async def _persist_check(
    session: AsyncSession,
    source_item_id: str,
    rule_id: str | None,
    result: str,
    reason: str,
    evidence: dict | None = None,
) -> None:
    item_repo = SourceItemRepository(session)
    await item_repo.save_eligibility_check(
        source_item_id=source_item_id,
        rule_id=rule_id,
        result=result,
        reason=reason,
        evidence_json=evidence or {},
        checked_at=_utcnow(),
    )
