"""Source items: the inventory of torrents seen on the sources."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SourceInstance
from app.database.repositories import (
    SourceItemRepository,
    SourceRepository,
    LabelRuleRepository,
    JobRepository,
)
from app.domain.models import JobStage, JobStatus
from app.database.session import get_session

router = APIRouter(tags=["source-items"])


class QueueRequest(BaseModel):
    force_transfer: bool = Field(
        False, description="Queue even though the item was skipped (e.g. already in the library)."
    )


@router.get("/source-items")
async def list_source_items(
    request: Request,
    source_id: str | None = Query(None),
    label: str | None = Query(None),
    eligibility: str | None = Query(
        None, description="Last classification, e.g. `eligible`, `already_available`."
    ),
    search: str | None = Query(None, description="Case-insensitive substring of the title."),
    has_job: bool | None = Query(
        None, description="Only items that have (true) or lack (false) a job."
    ),
    include_ignored: bool = Query(False, description="Include items marked ignored."),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """List torrents seen on the sources, newest first, with filters and paging."""
    repo = SourceItemRepository(session)
    items, total = await repo.list_filtered(
        source_id=source_id,
        label=label,
        eligibility=eligibility,
        search=search,
        has_job=has_job,
        include_ignored=include_ignored,
        offset=offset,
        limit=limit,
    )
    names = dict((await session.execute(select(SourceInstance.id, SourceInstance.name))).all())
    return {
        "items": [_item_to_dict(i, names) for i in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/source-items/{item_id}")
async def get_source_item(item_id: str, session: AsyncSession = Depends(get_session)):
    """Get one item with its media matches and eligibility check history."""
    repo = SourceItemRepository(session)
    obj = await repo.get(item_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Source item not found")
    src = await session.get(SourceInstance, obj.source_id)
    result = _item_to_dict(obj, {obj.source_id: src.name} if src else {})
    result["media_matches"] = [
        {
            "id": m.id,
            "media_type": m.media_type,
            "catalog_id": m.catalog_id,
            "title": "",
            "episode_ids": m.episode_ids_json,
            "confidence": m.confidence,
            "ambiguous": m.ambiguous,
        }
        for m in obj.media_matches
    ]
    result["eligibility_checks"] = [
        {
            "id": e.id,
            "result": e.result,
            "reason": e.reason,
            "checked_at": e.checked_at.isoformat(),
        }
        for e in obj.eligibility_checks
    ]
    return result


@router.post("/source-items/{item_id}/ignore")
async def ignore_item(item_id: str, session: AsyncSession = Depends(get_session)):
    """Hide an item from the default list and from automatic queueing."""
    from datetime import datetime, timezone

    repo = SourceItemRepository(session)
    obj = await repo.update(
        item_id, ignored_at=datetime.now(timezone.utc), last_eligibility="ignored"
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Source item not found")
    await session.commit()
    return {"status": "ignored", "item_id": item_id}


@router.post("/source-items/{item_id}/queue")
async def queue_item(
    item_id: str,
    body: QueueRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Create a job for an item, using the tag rule matching one of its labels.

    409 if the item already has an active job; 400 if no tag rule matches.
    """
    repo = SourceItemRepository(session)
    item = await repo.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Source item not found")

    # Check for existing active job (duplicate protection)
    job_repo = JobRepository(session)
    existing = await job_repo.get_active_for_item(item_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={"error": "duplicate_job", "job_id": existing.id, "status": existing.status},
        )

    # Find matching label rule
    if not item.labels_json:
        raise HTTPException(status_code=400, detail="No labels on this source item")

    label_repo = LabelRuleRepository(session)
    rule = None
    for label in item.labels_json:
        rule = await label_repo.get_by_source_label(item.source_id, label)
        if rule:
            break

    if not rule:
        raise HTTPException(
            status_code=400,
            detail="No matching label rule for any label on this item",
        )

    from app.services.jobs import create_job

    job = await create_job(
        session,
        item,
        rule,
        request.app.state.settings,
        approved=True,
        kind="job.created",
        message=f"Job created by user{' (force transfer)' if body.force_transfer else ''}",
    )
    await session.commit()
    return {"job_id": job.id, "status": job.status, "stage": job.stage}


def _item_to_dict(obj: Any, names: dict[str, str]) -> dict:
    return {
        "id": obj.id,
        "source_id": obj.source_id,
        "source_name": names.get(obj.source_id),
        "remote_id": obj.remote_id,
        "title": obj.title,
        "labels": obj.labels_json,
        "source_status": obj.source_status,
        "remote_path": obj.remote_path,
        "size_bytes": obj.size_bytes,
        "completed_at": obj.completed_at.isoformat() if obj.completed_at else None,
        "first_seen_at": obj.first_seen_at.isoformat() if obj.first_seen_at else None,
        "last_seen_at": obj.last_seen_at.isoformat() if obj.last_seen_at else None,
        "last_eligibility": obj.last_eligibility,
        "eligible_rule_id": obj.eligible_rule_id,
        "ignored_at": obj.ignored_at.isoformat() if obj.ignored_at else None,
    }
