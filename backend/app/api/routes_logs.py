"""Logs endpoint — exposes the recent in-memory application log buffer."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.logging_buffer import get_log_handler
from app.security import RequireAuth

logs_router = APIRouter(tags=["logs"])


@logs_router.get("/logs")
async def get_logs(
    user: RequireAuth,
    level: str | None = Query(
        default=None,
        description="Minimum severity to return (DEBUG, INFO, WARNING, ERROR).",
    ),
    search: str | None = Query(
        default=None, description="Case-insensitive substring on message or logger."
    ),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """Return recent application log entries, newest-first.

    Authentication is required: log lines can include internal detail that
    should not be exposed to unauthenticated callers.
    """
    handler = get_log_handler()
    if handler is None:
        return {"entries": [], "total": 0, "capacity": 0}
    return {
        "entries": handler.snapshot(level=level, search=search, limit=limit),
        "total": handler.count,
        "capacity": handler.capacity,
    }
