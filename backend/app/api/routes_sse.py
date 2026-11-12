"""SSE endpoint for job progress events."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

sse_router = APIRouter(tags=["events"])


@sse_router.get("/events")
async def events(request: Request) -> StreamingResponse:
    """Server-Sent Events for job/source/status/progress/config events.

    Sends periodic snapshots of active jobs. Clients should fall back to
    periodic refetch if the event buffer is too old.
    """
    async def event_stream() -> AsyncGenerator[str, None]:
        event_id = 0
        settings = request.app.state.settings

        # Send initial hello
        yield f"id: {event_id}\nevent: connected\ndata: {json.dumps({'status': 'connected'})}\n\n"

        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            event_id += 1

            # Send dashboard snapshot
            try:
                from app.database.session import get_session_factory
                from sqlalchemy import select, func
                from app.database.models import Job

                factory = get_session_factory(settings)
                async with factory() as session:
                    result = await session.execute(
                        select(Job).where(Job.status == "running").limit(50)
                    )
                    running_jobs = result.scalars().all()

                    snapshot = {
                        "jobs": [
                            {
                                "id": j.id,
                                "status": j.status,
                                "stage": j.stage,
                                "bytes_done": j.download_bytes_done,
                                "bytes_total": j.download_bytes_total,
                            }
                            for j in running_jobs
                        ]
                    }
                    yield f"id: {event_id}\nevent: snapshot\ndata: {json.dumps(snapshot)}\n\n"
            except Exception:
                yield f"id: {event_id}\nevent: error\ndata: {json.dumps({'error': 'db_error'})}\n\n"

            # Send every 2 seconds
            await asyncio.sleep(2.0)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
