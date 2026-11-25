"""Server-Sent Event streams of changes.

Streams carry changes only. Current state comes from the regular endpoints
(``GET /jobs``, ``GET /logs``): a client opens a stream, then fetches the
state, then applies events on top. Doing that on every (re)connect means
nothing missed while disconnected is lost.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes_logs import _UUID, _names
from app.database.models import Job, JobFile, StageRun
from app.database.session import get_session_factory
from app.logging_buffer import get_log_handler

router = APIRouter(tags=["events"])

TICK = 1.0  # seconds between change checks
# Jobs whose progress moves without touching the job row: running stages, and torrents
# downloading on the seedbox (discovery writes their progress to the stage run).
_LIVE = ("running", "waiting_source")
KEEPALIVE = 15.0  # seconds of silence before a comment line, so clients can spot dead streams


def _event(kind: str, data: Any) -> str:
    return f"event: {kind}\ndata: {json.dumps(data)}\n\n"


def _sse(request: Request, ticks: AsyncGenerator[list[str]]) -> StreamingResponse:
    async def stream() -> AsyncGenerator[str]:
        quiet_since = time.monotonic()
        async for chunks in ticks:
            if await request.is_disconnected():
                break
            if chunks:
                yield "".join(chunks)
                quiet_since = time.monotonic()
            elif time.monotonic() - quiet_since > KEEPALIVE:
                yield ": keepalive\n\n"
                quiet_since = time.monotonic()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def job_changes(
    session: AsyncSession, since: datetime | None, sent: dict[str, str]
) -> tuple[list[dict], datetime | None]:
    """Jobs that changed since the last check, and the new ``since`` cursor.

    ``sent`` maps job id to the last state sent, so heartbeats (which bump
    ``updated_at`` without changing anything visible) produce no events.
    Live jobs (_LIVE) are always checked: extract and seedbox progress live on the stage run
    and file rows (added up front, then flipped per transfer) do not touch the
    job row. ``files`` counts them by transfer status, so a file appearing or
    changing state is a change too.
    """
    # ponytail: unindexed updated_at scan; fine while retention keeps the jobs table small.
    is_live = Job.status.in_(_LIVE)
    changed = is_live if since is None else or_(Job.updated_at >= since, is_live)
    jobs = (await session.execute(select(Job).where(changed))).scalars().all()
    running = [j.id for j in jobs if j.status in _LIVE]
    files: dict[str, dict[str, int]] = {}
    for job_id, status, n in await session.execute(
        select(JobFile.job_id, JobFile.transfer_status, func.count())
        .where(JobFile.job_id.in_(running))
        .group_by(JobFile.job_id, JobFile.transfer_status)
    ):
        files.setdefault(job_id, {})[status] = n
    runs = dict(
        (
            await session.execute(
                select(StageRun.job_id, StageRun.progress_json).where(
                    StageRun.job_id.in_(running),
                    StageRun.status == "running",
                )
            )
        ).all()
    )

    out = []
    for j in jobs:
        stage_progress = runs.get(j.id) or None
        if j.stage == "transfer":
            done, total = j.download_bytes_done, j.download_bytes_total
        else:
            done, total = (
                (stage_progress or {}).get("bytes_done", 0),
                (stage_progress or {}).get("bytes_total", 0),
            )
        event = {
            "id": j.id,
            "status": j.status,
            "stage": j.stage,
            "error_code": j.error_code,
            "download_bytes_done": j.download_bytes_done,
            "download_bytes_total": j.download_bytes_total,
            "stage_progress": stage_progress,
            "progress": round(done * 100 / total) if j.status in _LIVE and total else None,
            "files": files.get(j.id),
        }
        key = json.dumps(event, sort_keys=True)
        if sent.get(j.id) != key:
            sent[j.id] = key
            out.append(event)
        if j.updated_at and (since is None or j.updated_at > since):
            since = j.updated_at
    return out, since


@router.get("/events/jobs")
async def job_events(request: Request) -> StreamingResponse:
    """Stream a ``job`` event whenever a job's status, stage, progress or files change.

    Changes only: fetch ``GET /jobs`` (or ``GET /jobs/{id}``) after connecting for current state.
    """
    factory = get_session_factory(request.app.state.settings)
    async with factory() as session:
        since = (await session.execute(select(func.max(Job.updated_at)))).scalar()

    async def ticks() -> AsyncGenerator[list[str]]:
        nonlocal since
        sent: dict[str, str] = {}
        while True:
            async with factory() as session:
                changes, since = await job_changes(session, since, sent)
            yield [_event("job", c) for c in changes]
            await asyncio.sleep(TICK)

    return _sse(request, ticks())


@router.get("/events/logs")
async def log_events(
    request: Request,
    level: str | None = Query(None, description="Minimum severity to send."),
    search: str | None = Query(None, description="Case-insensitive substring filter."),
) -> StreamingResponse:
    """Stream new log entries as ``log`` events (``{entries, names}``, oldest-first).

    Changes only: fetch ``GET /logs`` after connecting for the backlog.
    """
    handler = get_log_handler()
    seq = handler.seq if handler else 0
    factory = get_session_factory(request.app.state.settings)

    async def ticks() -> AsyncGenerator[list[str]]:
        nonlocal seq
        while True:
            entries = []
            if handler and handler.seq > seq:
                entries, seq = handler.since(seq, level=level, search=search)
            if entries:
                ids = {m for e in entries for m in _UUID.findall(e["message"])}
                async with factory() as session:
                    names = await _names(session, ids)
                yield [_event("log", {"entries": entries, "names": names})]
            else:
                yield []
            await asyncio.sleep(TICK)

    return _sse(request, ticks())
