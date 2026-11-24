"""Tagged torrents become jobs while they download; discovery tracks them until the seedbox is done."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.database.models import Job, SourceItem, StageRun
from app.database.repositories import LabelRuleRepository, SourceRepository
from app.database.session import get_session_factory
from app.domain.models import RemoteFileDTO, SourceItemDTO, SourceStatus

KEY = b"k" * 32


class FakeSource:
    """What rTorrent reports: ``items`` per scan, ``files`` per torrent; ``fail`` breaks the listing."""

    def __init__(self):
        self.items: list[SourceItemDTO] = []
        self.files: list[RemoteFileDTO] = []
        self.fail = False

    async def test_connection(self):
        return {"ok": True}

    async def list_items(self):
        if self.fail:
            raise ConnectionError("seedbox down")
        return self.items

    async def get_files(self, key):
        return self.files


def _dto(done=400, total=1000, status=SourceStatus.ACTIVE, complete=False, label="tv", rate=1234):
    return SourceItemDTO(
        remote_id="h1", name="Show.S01E01", labels=[label], status=status, total_bytes=total,
        remote_base_path="/dl", metadata={"complete": complete, "completed_bytes": done,
                                          "down_rate": rate, "message": "", "state": 1},
    )


@pytest.fixture
async def seedbox(app, settings, monkeypatch):
    """Source with an automatic 'tv' rule and a fake rTorrent; returns (source, scan, rule_id)."""
    from app.adapters import sources
    from app.services.discovery import DiscoveryService

    fake = FakeSource()
    monkeypatch.setattr(sources, "create_source_adapter", lambda *a, **k: fake)
    async with get_session_factory(settings)() as session:
        src = await SourceRepository(session).create(
            name="S", adapter_type="rtorrent", connection_config_json={}, credential_ref=""
        )
        rule = await LabelRuleRepository(session).create(
            source_id=src.id, label="tv", temporary_directory="/t", completed_directory="/c",
            automatic_processing=True,
        )
        await session.commit()
        source_id, rule_id = src.id, rule.id

    async def scan():
        return await DiscoveryService(settings, KEY).run_discovery_for_source(source_id)

    return fake, scan, rule_id


async def _jobs(settings) -> list[Job]:
    async with get_session_factory(settings)() as session:
        return list((await session.execute(select(Job))).scalars())


async def _download_run(settings, job_id) -> StageRun:
    async with get_session_factory(settings)() as session:
        return (await session.execute(
            select(StageRun).where(StageRun.job_id == job_id, StageRun.stage == "source_download")
        )).scalar_one()


async def test_incomplete_tagged_item_creates_downloading_job(seedbox, settings, monkeypatch):
    from app.services import classification

    fake, scan, _ = seedbox
    called = []
    monkeypatch.setattr(classification, "classify_item", lambda *a, **k: called.append(1))
    fake.items = [_dto()]
    await scan()

    [job] = await _jobs(settings)
    assert (job.stage, job.status) == ("source_download", "waiting_source")
    assert (await _download_run(settings, job.id)).status == "running"
    assert called == []


async def test_incomplete_item_on_manual_rule_still_gets_job(seedbox, settings):
    from app.database.models import SourceLabelRule

    fake, scan, rule_id = seedbox
    async with get_session_factory(settings)() as session:
        (await session.get(SourceLabelRule, rule_id)).automatic_processing = False
        await session.commit()
    fake.items = [_dto()]
    await scan()
    [job] = await _jobs(settings)
    assert job.stage == "source_download"


async def test_scan_updates_download_progress(seedbox, settings):
    fake, scan, _ = seedbox
    fake.items = [_dto(done=0)]
    await scan()
    fake.items = [_dto(done=400)]
    fake.files = [RemoteFileDTO(relative_path="a.mkv", size_bytes=1000, done_bytes=400)]
    await scan()

    [job] = await _jobs(settings)
    p = (await _download_run(settings, job.id)).progress_json
    assert (p["bytes_done"], p["bytes_total"], p["bps"]) == (400, 1000, 1234)
    assert p["files"] == [{"path": "a.mkv", "size_bytes": 1000, "done_bytes": 400}]


async def test_completion_moves_job_to_check_library(seedbox, settings):
    fake, scan, _ = seedbox
    fake.items = [_dto()]
    await scan()
    fake.items = [_dto(done=1000, status=SourceStatus.COMPLETED, complete=True)]
    await scan()

    [job] = await _jobs(settings)
    assert (job.stage, job.status) == ("check_library", "queued")
    run = await _download_run(settings, job.id)
    assert run.status == "succeeded" and run.ended_at is not None


async def test_paused_incomplete_torrent_stays_downloading(seedbox, settings):
    fake, scan, _ = seedbox
    fake.items = [_dto()]
    await scan()
    fake.items = [_dto(status=SourceStatus.STOPPED, complete=False)]
    await scan()

    [job] = await _jobs(settings)
    assert (job.stage, job.status) == ("source_download", "waiting_source")


async def test_removed_torrent_needs_attention(seedbox, settings):
    fake, scan, _ = seedbox
    fake.items = [_dto()]
    await scan()
    fake.items = []
    await scan()

    [job] = await _jobs(settings)
    assert (job.status, job.error_code) == ("needs_attention", "source_removed")


async def test_failed_scan_leaves_downloading_jobs_alone(seedbox, settings):
    fake, scan, _ = seedbox
    fake.items = [_dto()]
    await scan()
    fake.fail = True
    await scan()

    [job] = await _jobs(settings)
    assert (job.stage, job.status, job.error_code) == ("source_download", "waiting_source", None)


async def test_cancelled_download_not_recreated(seedbox, settings, auth_client):
    fake, scan, _ = seedbox
    fake.items = [_dto()]
    await scan()
    [job] = await _jobs(settings)
    assert (await auth_client.post(f"/api/v1/jobs/{job.id}/cancel")).status_code == 200
    await scan()

    [job] = await _jobs(settings)
    assert job.status == "cancelled"


async def test_waiting_library_job_requeued_on_scan(seedbox, settings):
    fake, scan, _ = seedbox
    fake.items = [_dto()]
    await scan()
    async with get_session_factory(settings)() as session:
        job = (await session.execute(select(Job))).scalar_one()
        job.stage, job.status = "check_library", "waiting_library"
        await session.commit()
    fake.items = [_dto(done=1000, status=SourceStatus.COMPLETED, complete=True)]
    await scan()

    [job] = await _jobs(settings)
    assert (job.stage, job.status) == ("check_library", "queued")


async def test_restart_complete_item_goes_to_check_library(seedbox, settings, auth_client):
    fake, scan, _ = seedbox
    fake.items = [_dto()]
    await scan()
    async with get_session_factory(settings)() as session:
        job = (await session.execute(select(Job))).scalar_one()
        job.stage, job.status = "move", "needs_attention"
        item = await session.get(SourceItem, job.source_item_id)
        item.source_status = "completed"
        item.remote_metadata_json = {**item.remote_metadata_json, "complete": True}
        await session.commit()

    assert (await auth_client.post(f"/api/v1/jobs/{job.id}/restart")).status_code == 200
    [job] = await _jobs(settings)
    assert (job.stage, job.status) == ("check_library", "queued")


async def test_restart_incomplete_item_goes_back_to_downloading(seedbox, settings, auth_client):
    fake, scan, _ = seedbox
    fake.items = [_dto()]
    await scan()
    [job] = await _jobs(settings)

    assert (await auth_client.post(f"/api/v1/jobs/{job.id}/restart")).status_code == 200
    [job] = await _jobs(settings)
    assert (job.stage, job.status) == ("source_download", "waiting_source")
    async with get_session_factory(settings)() as session:
        runs = (await session.execute(
            select(StageRun).where(StageRun.job_id == job.id, StageRun.status == "running")
        )).scalars().all()
    assert [r.stage for r in runs] == ["source_download"]


async def test_complete_on_first_sight_keeps_classification_rule(seedbox, settings, monkeypatch):
    from app.services import classification

    async def available(session, item, rule, library, key):
        return "already_available"

    monkeypatch.setattr(classification, "classify_item", available)
    fake, scan, _ = seedbox
    fake.items = [_dto(done=1000, status=SourceStatus.COMPLETED, complete=True)]
    await scan()
    assert await _jobs(settings) == []


async def test_complete_on_first_sight_queues_at_check_library(seedbox, settings):
    fake, scan, _ = seedbox
    fake.items = [_dto(done=1000, status=SourceStatus.COMPLETED, complete=True)]
    await scan()
    [job] = await _jobs(settings)
    assert (job.stage, job.status) == ("check_library", "queued")


async def test_manual_queue_is_preapproved(seedbox, settings, auth_client):
    from app.database.models import SourceLabelRule

    fake, scan, rule_id = seedbox
    async with get_session_factory(settings)() as session:
        (await session.get(SourceLabelRule, rule_id)).automatic_processing = False
        await session.commit()
    fake.items = [_dto(done=1000, status=SourceStatus.COMPLETED, complete=True)]
    await scan()
    assert await _jobs(settings) == []
    async with get_session_factory(settings)() as session:
        item_id = (await session.execute(select(SourceItem.id))).scalar_one()

    r = await auth_client.post(f"/api/v1/source-items/{item_id}/queue", json={})
    assert r.status_code == 200, r.text
    [job] = await _jobs(settings)
    assert (job.stage, job.config_snapshot_json["approved"]) == ("check_library", True)


@pytest.mark.parametrize("action", ["retry", "resume"])
async def test_retry_or_resume_during_download_goes_back_to_waiting(seedbox, settings, auth_client, action):
    """No worker runs source_download, so 'queued' there would never move."""
    fake, scan, _ = seedbox
    fake.items = [_dto()]
    await scan()
    fake.items = []
    await scan()  # removed: needs_attention
    [job] = await _jobs(settings)
    if action == "resume":
        assert (await auth_client.post(f"/api/v1/jobs/{job.id}/pause")).status_code == 200

    r = await auth_client.post(f"/api/v1/jobs/{job.id}/{action}")
    assert r.status_code == 200
    assert r.json()["status"] == "waiting_source"
    [job] = await _jobs(settings)
    assert (job.stage, job.status) == ("source_download", "waiting_source")


async def test_progress_scan_skips_library(seedbox, settings, monkeypatch):
    """5-second ticks refresh downloads only: no library lookups, no requeues."""
    from app.services import classification
    from app.services.discovery import DiscoveryService

    fake, scan, _ = seedbox
    fake.items = [_dto()]
    await scan()
    [job] = await _jobs(settings)
    async with get_session_factory(settings)() as session:
        source_id = (await session.get(SourceItem, job.source_item_id)).source_id

    calls = []

    async def counting(*a, **k):
        calls.append(1)
        return "missing"

    monkeypatch.setattr(classification, "classify_item", counting)
    done = _dto(done=1000, status=SourceStatus.COMPLETED, complete=True)
    complete_other = done.model_copy(update={"remote_id": "h2", "name": "Other"})
    fake.items = [_dto(done=700), complete_other]
    await DiscoveryService(settings, KEY).run_discovery_for_source(source_id, progress_only=True)

    assert calls == []  # the complete, never-classified item waits for a full scan
    p = (await _download_run(settings, job.id)).progress_json
    assert p["bytes_done"] == 700
    assert len(await _jobs(settings)) == 1


async def test_progress_scan_leaves_waiting_library_alone(seedbox, settings):
    from app.services.discovery import DiscoveryService

    fake, scan, _ = seedbox
    fake.items = [_dto()]
    await scan()
    async with get_session_factory(settings)() as session:
        job = (await session.execute(select(Job))).scalar_one()
        job.stage, job.status = "check_library", "waiting_library"
        source_id = (await session.get(SourceItem, job.source_item_id)).source_id
        await session.commit()
    fake.items = [_dto(done=1000, status=SourceStatus.COMPLETED, complete=True)]
    await DiscoveryService(settings, KEY).run_discovery_for_source(source_id, progress_only=True)

    [job] = await _jobs(settings)
    assert job.status == "waiting_library"


async def test_progress_scan_still_creates_downloading_jobs(seedbox, settings):
    from app.services.discovery import DiscoveryService

    fake, scan, _ = seedbox
    await scan()  # empty seedbox
    async with get_session_factory(settings)() as session:
        from app.database.models import SourceInstance
        source_id = (await session.execute(select(SourceInstance.id))).scalar_one()
    fake.items = [_dto()]
    await DiscoveryService(settings, KEY).run_discovery_for_source(source_id, progress_only=True)

    [job] = await _jobs(settings)
    assert job.stage == "source_download"


@pytest.mark.parametrize("status", ["waiting_library", "waiting_approval", "queued", "retry_wait"])
async def test_removed_torrent_ends_job_parked_before_transfer(seedbox, settings, status):
    """Nothing was transferred yet, so a torrent deleted from the seedbox just ends the job."""
    fake, scan, _ = seedbox
    fake.items = [_dto()]
    await scan()
    async with get_session_factory(settings)() as session:
        job = (await session.execute(select(Job))).scalar_one()
        job.stage, job.status = "check_library", status
        await session.commit()
    fake.items = []
    await scan()

    [job] = await _jobs(settings)
    assert (job.status, job.error_code) == ("skipped", "source_removed")
    assert job.ended_at is not None


async def test_removed_torrent_leaves_running_or_later_jobs(seedbox, settings):
    fake, scan, _ = seedbox
    fake.items = [_dto()]
    await scan()
    async with get_session_factory(settings)() as session:
        job = (await session.execute(select(Job))).scalar_one()
        job.stage, job.status = "transfer", "queued"
        await session.commit()
    fake.items = []
    await scan()

    [job] = await _jobs(settings)
    assert (job.stage, job.status) == ("transfer", "queued")
