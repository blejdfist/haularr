"""Source items (inventory) endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import SourceItemRepository, SourceRepository, LabelRuleRepository, JobRepository
from app.domain.models import JobStage, JobStatus
from app.security import RequireAuth

source_items_router = APIRouter(tags=["source-items"])


async def get_session(request: Request):
    from app.database.session import get_session_factory
    from app.settings import Settings
    settings: Settings = request.app.state.settings
    factory = get_session_factory(settings)
    async with factory() as session:
        yield session


class QueueRequest(BaseModel):
    force_transfer: bool = False
    idempotency_key: str | None = None


class BulkQueueRequest(BaseModel):
    source_item_ids: list[str]
    force_transfer: bool = False


@source_items_router.get("/source-items")
async def list_source_items(
    request: Request,
    source_id: str | None = Query(None),
    label: str | None = Query(None),
    eligibility: str | None = Query(None),
    search: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    repo = SourceItemRepository(session)
    items, total = await repo.list_filtered(
        source_id=source_id,
        label=label,
        eligibility=eligibility,
        search=search,
        offset=offset,
        limit=limit,
    )
    return {
        "items": [_item_to_dict(i) for i in items],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@source_items_router.get("/source-items/{item_id}")
async def get_source_item(item_id: str, session: AsyncSession = Depends(get_session)):
    repo = SourceItemRepository(session)
    obj = await repo.get(item_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Source item not found")
    result = _item_to_dict(obj)
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


@source_items_router.post("/source-items/{item_id}/recheck")
async def recheck_item(item_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    repo = SourceItemRepository(session)
    item = await repo.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Source item not found")

    await repo.update(item_id, last_eligibility="classifying")
    await session.commit()

    # Trigger classification via discovery supervisor if available
    # (async background, doesn't block response)
    if hasattr(request.app.state, "supervisor"):
        import asyncio
        asyncio.create_task(request.app.state.supervisor.trigger_scan(item.source_id))

    return {"status": "rechecking", "item_id": item_id}


@source_items_router.post("/source-items/{item_id}/ignore")
async def ignore_item(item_id: str, session: AsyncSession = Depends(get_session)):
    from datetime import datetime, timezone
    repo = SourceItemRepository(session)
    obj = await repo.update(item_id, ignored_at=datetime.now(timezone.utc), last_eligibility="ignored")
    if not obj:
        raise HTTPException(status_code=404, detail="Source item not found")
    await session.commit()
    return {"status": "ignored", "item_id": item_id}


@source_items_router.post("/source-items/{item_id}/queue")
async def queue_item(
    item_id: str,
    body: QueueRequest,
    session: AsyncSession = Depends(get_session),
):
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

    # Idempotency: check for a recently completed job with the same key
    if body.idempotency_key:
        from sqlalchemy import select as sa_select
        from app.database.models import Job as JobModel
        from sqlalchemy.ext.asyncio import AsyncSession as AsyncSessionType
        idem_result = await session.execute(
            sa_select(JobModel).where(
                JobModel.source_item_id == item_id,
                JobModel.idempotency_key == body.idempotency_key,
            ).limit(1)
        )
        idem_job = idem_result.scalar_one_or_none()
        if idem_job:
            return {"job_id": idem_job.id, "status": idem_job.status, "stage": idem_job.stage}

    # Find matching label rule
    if not item.labels_json:
        raise HTTPException(status_code=400, detail="No labels on this source item")

    label_repo = LabelRuleRepository(session)
    rule = None
    for label in item.labels_json:
        rule = await label_repo.get_by_source_label(item.source_id, label)
        if rule:
            break

    if not rule and not body.force_transfer:
        raise HTTPException(
            status_code=400,
            detail="No matching label rule; cannot auto-queue",
        )

    # Find a rule even for force_transfer
    if not rule:
        raise HTTPException(
            status_code=400,
            detail="No matching label rule for any label on this item",
        )

    # Build config snapshot
    source_repo = SourceRepository(session)
    source = await source_repo.get(item.source_id)

    config_snapshot = {
        "source_id": item.source_id,
        "source_name": source.name if source else "",
        "label": rule.label,
        "transfer_id": rule.transfer_override_id or (source.default_transfer_id if source else None),
        "library_instance_id": rule.library_instance_id,
        "temporary_directory": rule.temporary_directory,
        "completed_directory": rule.completed_directory,
        "retry_limit": 5,
        "stage_lease_seconds": 90,
    }

    import uuid
    from datetime import datetime, timezone

    job = await job_repo.create(
        source_item_id=item_id,
        rule_id=rule.id,
        config_snapshot_json=config_snapshot,
        priority=rule.priority,
        status="queued",
        stage=JobStage.RESOLVE_SOURCE.value,
        idempotency_key=body.idempotency_key,
    )
    await job_repo.add_event(
        job_id=job.id,
        severity="info",
        kind="job.created",
        message=f"Job created {'(force transfer)' if body.force_transfer else ''}",
        details_json={"force_transfer": body.force_transfer},
    )
    await session.commit()
    return {"job_id": job.id, "status": job.status, "stage": job.stage}


@source_items_router.post("/source-items/bulk-queue")
async def bulk_queue(body: BulkQueueRequest, session: AsyncSession = Depends(get_session)):
    results = []
    for item_id in body.source_item_ids:
        try:
            result = await queue_item(item_id, QueueRequest(force_transfer=body.force_transfer), session)
            results.append({"item_id": item_id, "job_id": result["job_id"], "status": "queued"})
        except HTTPException as exc:
            results.append({"item_id": item_id, "error": exc.detail, "status": "error"})
    await session.commit()
    return {"results": results}


def _item_to_dict(obj: Any) -> dict:
    return {
        "id": obj.id,
        "source_id": obj.source_id,
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
