"""Dashboard aggregate endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Job, SourceInstance, SourceItem

dashboard_router = APIRouter(tags=["dashboard"])


async def get_session(request: Request):
    from app.database.session import get_session_factory
    from app.settings import Settings
    settings: Settings = request.app.state.settings
    factory = get_session_factory(settings)
    async with factory() as session:
        yield session


@dashboard_router.get("/dashboard")
async def get_dashboard(session: AsyncSession = Depends(get_session)):
    """Aggregate counts, queue, capacity, source health."""

    # Job counts by status
    status_counts = {}
    result = await session.execute(
        select(Job.status, func.count(Job.id)).group_by(Job.status)
    )
    for status_val, count in result.all():
        status_counts[status_val] = count

    # Source counts
    source_result = await session.execute(
        select(SourceInstance.adapter_type, func.count(SourceInstance.id)).group_by(
            SourceInstance.adapter_type
        )
    )
    source_counts = {row[0]: row[1] for row in source_result.all()}

    # Source item counts
    item_result = await session.execute(
        select(func.count(SourceItem.id))
    )
    total_items = item_result.scalar_one()

    # Active jobs
    active_result = await session.execute(
        select(func.count(Job.id)).where(Job.status == "running")
    )
    active_jobs = active_result.scalar_one()

    return {
        "jobs": {
            "active": active_jobs,
            "queued": status_counts.get("queued", 0),
            "running": status_counts.get("running", 0),
            "retry_wait": status_counts.get("retry_wait", 0),
            "needs_attention": status_counts.get("needs_attention", 0),
            "failed": status_counts.get("failed", 0),
            "completed": status_counts.get("completed", 0),
            "paused": status_counts.get("paused", 0),
        },
        "sources": source_counts,
        "source_items_total": total_items,
        "capacity": {
            "max_concurrent_download_jobs": 3,
            "active_downloads": active_jobs,
        },
    }
