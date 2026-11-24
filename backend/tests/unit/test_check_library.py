"""check_library: the library verdict and the rule decide whether the job goes on, waits or ends."""

from __future__ import annotations

import pytest

from app.database.models import Job, SourceLabelRule
from app.database.session import get_session_factory
from app.domain.models import StageRunStatus
from tests.unit.test_waiting_fetch import _get, _job


@pytest.fixture
def verdict(monkeypatch):
    """Set ``verdict[0]`` to the eligibility classify_item should return."""
    from app.services import classification

    box = ["missing"]

    async def fake_classify(session, item, rule, library, master_key):
        return box[0]

    monkeypatch.setattr(classification, "classify_item", fake_classify)
    return box


async def _gated_job(settings, automatic=True, approved=False) -> str:
    _, job_id = await _job(settings, "running")
    async with get_session_factory(settings)() as session:
        job = await session.get(Job, job_id)
        job.stage = "check_library"
        job.config_snapshot_json = {**job.config_snapshot_json, "approved": approved}
        (await session.get(SourceLabelRule, job.rule_id)).automatic_processing = automatic
        await session.commit()
    return job_id


async def _run(settings, job_id):
    from app.jobs.scheduler import JobScheduler, StageSemaphore

    sem = StageSemaphore(1)
    await sem.acquire()
    await JobScheduler(settings)._run_job(job_id, "check_library", "tok", sem)
    return await _get(settings, job_id)


async def test_check_library_missing_continues(app, settings, verdict):
    from app.jobs.runner import JobRunner

    job_id = await _gated_job(settings)
    result = await JobRunner(settings, job_id, "check_library", "tok").execute()
    assert result.status == StageRunStatus.SUCCEEDED


async def test_check_library_not_registered_parks(app, settings, verdict):
    verdict[0] = "not_registered"
    job = await _run(settings, await _gated_job(settings))
    assert (job.status, job.stage) == ("waiting_library", "check_library")
    assert job.ended_at is None


async def test_check_library_already_available_skips(app, settings, verdict):
    verdict[0] = "already_available"
    job = await _run(settings, await _gated_job(settings))
    assert job.status == "skipped"
    assert job.ended_at is not None


async def test_check_library_needs_review_needs_attention(app, settings, verdict):
    verdict[0] = "needs_review"
    job = await _run(settings, await _gated_job(settings))
    assert (job.status, job.error_code) == ("needs_attention", "needs_review")


async def test_check_library_unreachable_retries(app, settings, verdict):
    verdict[0] = "waiting_library"
    job = await _run(settings, await _gated_job(settings))
    assert (job.status, job.error_code) == ("retry_wait", "library_unreachable")


async def test_check_library_manual_rule_waits_for_approval(app, settings, verdict):
    job = await _run(settings, await _gated_job(settings, automatic=False))
    assert (job.status, job.error_code) == ("waiting_approval", "awaiting_approval")


async def test_check_library_approved_job_continues(app, settings, verdict):
    job = await _run(settings, await _gated_job(settings, automatic=False, approved=True))
    assert (job.status, job.stage) == ("queued", "transfer")


async def test_approve_requeues_waiting_job(auth_client, settings):
    _, job_id = await _job(settings, "waiting_approval", error_code="awaiting_approval")
    r = await auth_client.post(f"/api/v1/jobs/{job_id}/approve")
    assert r.status_code == 200, r.text
    job = await _get(settings, job_id)
    assert job.status == "queued"
    assert job.error_code is None
    assert job.config_snapshot_json["approved"] is True


async def test_approve_rejects_other_status(auth_client, settings):
    _, job_id = await _job(settings, "running")
    r = await auth_client.post(f"/api/v1/jobs/{job_id}/approve")
    assert r.status_code == 409


@pytest.mark.parametrize("v", ["not_registered", "needs_review", "already_available"])
async def test_skip_library_check_continues_whatever_the_verdict(app, settings, verdict, v):
    """A multi-movie pack ("Tron Trilogy") never parses as one movie; the user can wave it through."""
    verdict[0] = v
    job_id = await _gated_job(settings, automatic=False)
    async with get_session_factory(settings)() as session:
        job = await session.get(Job, job_id)
        job.config_snapshot_json = {**job.config_snapshot_json, "skip_library": True}
        await session.commit()
    job = await _run(settings, job_id)
    assert (job.status, job.stage) == ("queued", "transfer")


async def _staged(settings, stage, status):
    _, job_id = await _job(settings, status)
    async with get_session_factory(settings)() as session:
        (await session.get(Job, job_id)).stage = stage
        await session.commit()
    return job_id


@pytest.mark.parametrize("status", ["waiting_library", "waiting_approval", "needs_attention"])
async def test_skip_library_requeues_parked_job(auth_client, settings, status):
    job_id = await _staged(settings, "check_library", status)
    r = await auth_client.post(f"/api/v1/jobs/{job_id}/skip-library")
    assert r.status_code == 200, r.text
    job = await _get(settings, job_id)
    assert (job.status, job.error_code) == ("queued", None)
    assert job.config_snapshot_json["skip_library"] is True


async def test_skip_library_while_downloading_is_remembered(auth_client, settings):
    job_id = await _staged(settings, "source_download", "waiting_source")
    r = await auth_client.post(f"/api/v1/jobs/{job_id}/skip-library")
    assert r.status_code == 200, r.text
    job = await _get(settings, job_id)
    assert job.status == "waiting_source"
    assert job.config_snapshot_json["skip_library"] is True


@pytest.mark.parametrize("stage,status", [("check_library", "running"), ("transfer", "queued")])
async def test_skip_library_rejected_once_past_or_running(auth_client, settings, stage, status):
    job_id = await _staged(settings, stage, status)
    r = await auth_client.post(f"/api/v1/jobs/{job_id}/skip-library")
    assert r.status_code == 409


async def test_skip_library_reopens_job_ended_as_already_in_library(auth_client, settings):
    """A pack can parse as one of its movies ("Tron" 1982) and look already available."""
    from datetime import datetime, timezone

    job_id = await _staged(settings, "check_library", "skipped")
    async with get_session_factory(settings)() as session:
        job = await session.get(Job, job_id)
        job.error_code, job.ended_at = "already_available", datetime.now(timezone.utc)
        await session.commit()
    r = await auth_client.post(f"/api/v1/jobs/{job_id}/skip-library")
    assert r.status_code == 200, r.text
    job = await _get(settings, job_id)
    assert (job.status, job.ended_at) == ("queued", None)


async def test_skip_library_rejects_cancelled_job(auth_client, settings):
    job_id = await _staged(settings, "check_library", "cancelled")
    r = await auth_client.post(f"/api/v1/jobs/{job_id}/skip-library")
    assert r.status_code == 409
