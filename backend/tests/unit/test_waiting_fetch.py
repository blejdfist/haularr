"""Jobs without a fetch config wait on the seedbox and resume when fetch is saved."""

from __future__ import annotations

import pytest

from app.database.models import Job, SourceInstance, SourceItem
from app.database.repositories import LabelRuleRepository, SourceRepository
from app.database.session import get_session_factory

FETCH = {"host": "ftp.example", "port": 21, "username": "u", "password": "p", "path_mappings": []}


async def _job(settings, status="queued", source_name="S", error_code=None) -> tuple[str, str]:
    async with get_session_factory(settings)() as session:
        source = await SourceRepository(session).create(
            name=source_name, adapter_type="rtorrent", connection_config_json={}, credential_ref=""
        )
        rule = await LabelRuleRepository(session).create(
            source_id=source.id, label="tv", temporary_directory="/t", completed_directory="/c"
        )
        item = SourceItem(source_id=source.id, remote_id="h", title="T", labels_json=["tv"],
                          source_status="completed", remote_path="/p", size_bytes=1)
        session.add(item)
        await session.flush()
        job = Job(source_item_id=item.id, rule_id=rule.id, stage="download", status=status,
                  error_code=error_code,
                  config_snapshot_json={"source_id": source.id, "transfer_id": None,
                                        "temporary_directory": "/t"})
        session.add(job)
        await session.commit()
        return source.id, job.id


async def _get(settings, job_id) -> Job:
    async with get_session_factory(settings)() as session:
        return await session.get(Job, job_id)


@pytest.mark.asyncio
async def test_download_without_transfer_parks_waiting_source(app, settings):
    from app.jobs.scheduler import JobScheduler, StageSemaphore

    _, job_id = await _job(settings)
    sched = JobScheduler(settings)
    sem = StageSemaphore(1)
    await sem.acquire()
    await sched._run_job(job_id, "download", "tok", sem)

    job = await _get(settings, job_id)
    assert job.status == "waiting_source"
    assert job.error_code == "no_transfer_config"
    assert job.error_detail == "Done on seedbox — no fetch configured"
    assert job.stage == "download"


@pytest.mark.asyncio
async def test_saving_fetch_resumes_waiting_jobs(auth_client, settings):
    a, job_a = await _job(settings, "waiting_source", "A", "no_transfer_config")
    _, job_b = await _job(settings, "waiting_source", "B", "no_transfer_config")

    r = await auth_client.patch(f"/api/v1/sources/{a}", json={"fetch": FETCH})
    assert r.status_code == 200, r.text

    async with get_session_factory(settings)() as session:
        transfer_id = (await session.get(SourceInstance, a)).default_transfer_id
    ja, jb = await _get(settings, job_a), await _get(settings, job_b)
    assert ja.status == "queued"
    assert ja.config_snapshot_json["transfer_id"] == transfer_id
    assert ja.error_code is None
    assert jb.status == "waiting_source"
    assert jb.config_snapshot_json["transfer_id"] is None
