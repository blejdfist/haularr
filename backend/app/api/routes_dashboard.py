"""Dashboard aggregate endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, and_
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
    """Aggregate counts, queue, capacity, source health, disk space."""

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

    # Enabled sources
    enabled_result = await session.execute(
        select(func.count(SourceInstance.id)).where(SourceInstance.enabled == True)  # noqa: E712
    )
    enabled_sources = enabled_result.scalar_one()

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

    # Completed today
    from datetime import datetime, timedelta, timezone
    today_start = datetime.now(timezone.utc) - timedelta(hours=24)
    completed_today_result = await session.execute(
        select(func.count(Job.id)).where(
            and_(
                Job.status == "completed",
                Job.ended_at >= today_start,
            )
        )
    )
    completed_today = completed_today_result.scalar_one()

    completed_7d = (
        await session.execute(
            select(func.count(Job.id)).where(
                Job.status.in_(["completed", "completed_with_warnings"]),
                Job.ended_at >= datetime.now(timezone.utc) - timedelta(days=7),
            )
        )
    ).scalar_one()

    source_health = [
        {
            "id": s.id,
            "name": s.name,
            "last_scan_at": s.last_scan_at.isoformat() if s.last_scan_at else None,
            "last_scan_error": s.last_scan_error,
        }
        for s in (await session.execute(select(SourceInstance))).scalars().all()
    ]

    # Recently completed/failed (last 10)
    recent_result = await session.execute(
        select(Job)
        .where(Job.ended_at.is_not(None))
        .order_by(Job.ended_at.desc())
        .limit(10)
    )
    recent_jobs = [
        {
            "id": j.id,
            "status": j.status,
            "stage": j.stage,
            "ended_at": j.ended_at.isoformat() if j.ended_at else None,
        }
        for j in recent_result.scalars().all()
    ]

    return {
        "jobs": {
            "active": active_jobs,
            "queued": status_counts.get("queued", 0),
            "running": status_counts.get("running", 0),
            "retry_wait": status_counts.get("retry_wait", 0),
            "needs_attention": status_counts.get("needs_attention", 0),
            "failed": status_counts.get("failed", 0),
            "completed": status_counts.get("completed", 0),
            "completed_today": completed_today,
            "completed_7d": completed_7d,
            "by_status": status_counts,
            "paused": status_counts.get("paused", 0),
            "cancelled": status_counts.get("cancelled", 0),
        },
        "source_health": source_health,
        "sources": source_counts,
        "enabled_sources": enabled_sources,
        "source_items_total": total_items,
        "capacity": {
            "max_concurrent_download_jobs": 3,
            "active_downloads": active_jobs,
        },
        "recent_jobs": recent_jobs,
        "disk": _get_disk_info(),
    }


def _get_disk_info() -> dict:
    """Get disk usage info for common temp/completed paths."""
    import shutil
    import os

    paths_to_check = [
        ("temp", "/data/temp"),
        ("completed", "/data/completed"),
        ("config", "/config"),
    ]

    disk_info = {}
    for label, path in paths_to_check:
        try:
            if os.path.exists(path):
                total, used, free = shutil.disk_usage(path)
                disk_info[label] = {
                    "path": path,
                    "total_bytes": total,
                    "used_bytes": used,
                    "free_bytes": free,
                    "free_percent": round(free / total * 100, 1) if total > 0 else 0,
                }
            else:
                disk_info[label] = {"path": path, "available": False}
        except Exception:
            disk_info[label] = {"path": path, "available": False, "error": "check failed"}

    return disk_info
