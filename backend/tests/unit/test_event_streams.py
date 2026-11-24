"""Change streams: only real job changes become events; logs stream from a cursor."""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import func, select, update

from app.api.routes_sse import job_changes
from app.database.models import Job, JobFile
from app.database.session import get_session_factory
from app.logging_buffer import install_log_handler
from tests.unit.test_jobs_list import _seed


@pytest.mark.asyncio
async def test_job_changes_skip_heartbeats_and_report_new_jobs(app, settings):
    await _seed(settings, [("running", 1)])
    factory = get_session_factory(settings)
    sent: dict[str, str] = {}
    async with factory() as s:
        changes, since = await job_changes(s, None, sent)
        assert [c["status"] for c in changes] == ["running"]
        job_id = changes[0]["id"]

        # Heartbeat: updated_at moves, nothing visible changes.
        await s.execute(update(Job).where(Job.id == job_id).values(lease_expires_at=func.now()))
        await s.commit()
        changes, since = await job_changes(s, since, sent)
        assert changes == []

        await s.execute(update(Job).where(Job.id == job_id).values(
            download_bytes_done=50, download_bytes_total=100, stage="download"))
        await s.commit()
        changes, since = await job_changes(s, since, sent)
        assert [(c["id"], c["progress"]) for c in changes] == [(job_id, 50)]

        # A file row appearing (or changing state) on a running job is a change.
        s.add(JobFile(job_id=job_id, remote_relpath="a.mkv"))
        await s.commit()
        changes, since = await job_changes(s, since, sent)
        assert [(c["id"], c["files"]) for c in changes] == [(job_id, {"pending": 1})]

        # A job created between checks shows up.
        first = await s.get(Job, job_id)
        s.add(Job(source_item_id=first.source_item_id, rule_id=first.rule_id,
                  config_snapshot_json={}, status="queued"))
        await s.commit()
        changes, since = await job_changes(s, since, sent)
        assert [c["status"] for c in changes] == ["queued"]
        assert len((await s.execute(select(Job))).scalars().all()) == 2


@pytest.mark.asyncio
async def test_job_stream_requires_auth(client):
    assert (await client.get("/api/v1/events/jobs")).status_code == 401
    assert (await client.get("/api/v1/events/logs")).status_code == 401


def test_log_since_returns_only_newer_matching_entries():
    handler = install_log_handler()
    log = logging.getLogger("test.logs.since")
    log.setLevel(logging.DEBUG)
    log.info("before")
    seq = handler.seq
    log.info("after info")
    log.warning("after warning")
    entries, last = handler.since(seq, level="WARNING")
    assert [e["message"] for e in entries] == ["after warning"]
    assert last == handler.seq
    assert handler.since(last)[0] == []
