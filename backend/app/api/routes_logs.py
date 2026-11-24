"""Logs endpoint — exposes the recent in-memory application log buffer."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.database.models import Job, LibraryInstance, SourceInstance, SourceItem
from app.logging_buffer import get_log_handler

router = APIRouter(tags=["system"])

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


async def _names(session: AsyncSession, ids: set[str]) -> dict[str, str]:
    """Display names for the source/library/job/item ids that appear in log lines."""
    if not ids:
        return {}
    names: dict[str, str] = {}
    for model, col in (
        (SourceInstance, SourceInstance.name),
        (LibraryInstance, LibraryInstance.name),
        (SourceItem, SourceItem.title),
    ):
        rows = await session.execute(select(model.id, col).where(model.id.in_(ids)))
        names.update({i: n for i, n in rows if n})
    rows = await session.execute(select(Job.id, Job.config_snapshot_json).where(Job.id.in_(ids)))
    names.update({i: snap["title"] for i, snap in rows if (snap or {}).get("title")})
    return names


@router.get("/logs")
async def get_logs(
    level: str | None = Query(
        default=None,
        description="Minimum severity to return (DEBUG, INFO, WARNING, ERROR).",
    ),
    search: str | None = Query(
        default=None, description="Case-insensitive substring on message or logger."
    ),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return recent application log entries, newest-first.

    `names` maps ids mentioned in the messages to the entity's display name.

    Authentication is required: log lines can include internal detail that
    should not be exposed to unauthenticated callers.
    """
    handler = get_log_handler()
    if handler is None:
        return {"entries": [], "total": 0, "capacity": 0, "names": {}}
    entries = handler.snapshot(level=level, search=search, limit=limit)
    ids = {m for e in entries for m in _UUID.findall(e["message"])}
    return {
        "entries": entries,
        "total": handler.count,
        "capacity": handler.capacity,
        "names": await _names(session, ids),
    }
