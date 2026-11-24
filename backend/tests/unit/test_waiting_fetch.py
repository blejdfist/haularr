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


@pytest.mark.asyncio
async def test_download_uses_fetch_saved_after_job_was_created(auth_client, settings):
    """Snapshot taken before fetch existed must not park once the source has fetch."""
    from app.jobs.scheduler import JobScheduler, StageSemaphore

    source_id, job_id = await _job(settings)
    r = await auth_client.patch(f"/api/v1/sources/{source_id}", json={"fetch": FETCH})
    assert r.status_code == 200, r.text

    sched = JobScheduler(settings)
    sem = StageSemaphore(1)
    await sem.acquire()
    await sched._run_job(job_id, "download", "tok", sem)

    job = await _get(settings, job_id)
    assert job.error_code != "no_transfer_config"
    assert job.status != "waiting_source"


@pytest.mark.asyncio
async def test_manual_retry_resets_attempts(auth_client, settings):
    _, job_id = await _job(settings, "needs_attention")
    async with get_session_factory(settings)() as session:
        job = await session.get(Job, job_id)
        job.attempts = settings.retry_limit
        await session.commit()

    r = await auth_client.post(f"/api/v1/jobs/{job_id}/retry")
    assert r.status_code == 200, r.text
    job = await _get(settings, job_id)
    assert job.status == "queued"
    assert job.attempts == 0  # a retried job gets the full automatic-retry budget again


async def _runs(settings, job_id):
    from sqlalchemy import select
    from app.database.models import StageRun
    async with get_session_factory(settings)() as session:
        return (await session.execute(select(StageRun).where(StageRun.job_id == job_id))).scalars().all()


@pytest.mark.asyncio
async def test_stage_run_is_closed_with_result(app, settings):
    from app.jobs.runner import JobRunner

    _, job_id = await _job(settings)
    result = await JobRunner(settings, job_id, "notify", "tok").execute()
    [run] = await _runs(settings, job_id)
    assert run.status == result.status.value == "succeeded"
    assert run.ended_at is not None


@pytest.mark.asyncio
async def test_stage_run_is_closed_when_handler_crashes(app, settings, monkeypatch):
    from app.jobs.runner import JobRunner

    async def boom(self, job, run_id):
        raise RuntimeError("kaput")

    monkeypatch.setattr(JobRunner, "_stage_notify", boom)
    _, job_id = await _job(settings)
    with pytest.raises(RuntimeError):
        await JobRunner(settings, job_id, "notify", "tok").execute()
    [run] = await _runs(settings, job_id)
    assert run.status == "failed"
    assert run.ended_at is not None
    assert "kaput" in run.error_detail


@pytest.mark.asyncio
async def test_update_progress_writes_stage_run(app, settings):
    from app.database.repositories import JobRepository
    from app.jobs.runner import JobRunner

    _, job_id = await _job(settings)
    async with get_session_factory(settings)() as session:
        run = await JobRepository(session).add_stage_run(job_id=job_id, stage="download", attempt=1, status="running")
        await session.commit()
    await JobRunner(settings, job_id, "download", "tok")._update_progress(run.id, {"files": 1})
    [saved] = await _runs(settings, job_id)
    assert saved.progress_json == {"files": 1}


@pytest.mark.asyncio
async def test_heartbeat_renews_lease(app, settings):
    from app.jobs.runner import JobRunner

    _, job_id = await _job(settings)
    async with get_session_factory(settings)() as session:
        (await session.get(Job, job_id)).worker_token = "tok"
        await session.commit()
    await JobRunner(settings, job_id, "download", "tok")._renew_lease()
    assert (await _get(settings, job_id)).lease_expires_at is not None


async def test_restart_runs_job_from_the_beginning(auth_client, settings):
    """Restart: back to the first stage with a clean slate, files re-downloaded."""
    from sqlalchemy import select
    from app.database.models import JobFile

    _, job_id = await _job(settings, "needs_attention")
    async with get_session_factory(settings)() as session:
        job = await session.get(Job, job_id)
        job.stage, job.attempts, job.download_bytes_done = "publish", 3, 10
        session.add(JobFile(job_id=job_id, remote_relpath="a.mkv", size_bytes=10))
        await session.commit()

    r = await auth_client.post(f"/api/v1/jobs/{job_id}/restart")
    assert r.status_code == 200, r.text
    job = await _get(settings, job_id)
    assert (job.stage, job.status, job.attempts, job.download_bytes_done) == ("resolve_source", "queued", 0, 0)
    async with get_session_factory(settings)() as session:
        assert not (await session.execute(select(JobFile).where(JobFile.job_id == job_id))).scalars().all()
