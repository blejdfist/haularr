"""Download stage: re-runs must not re-fetch finished files, crash on them, or duplicate file rows."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.database.models import Job, JobFile, TransferEndpoint, TransferInstance
from app.database.session import get_session_factory
from app.domain.models import RemoteFileDTO, StageRunStatus, TransferResult
from tests.unit.test_waiting_fetch import _job

DATA = b"0123456789"


@pytest.fixture
def stage(app, settings, tmp_path, monkeypatch):
    """A download job for item 'T' with one 10-byte file a.mkv; returns (run, transfer_calls)."""
    from app.adapters import sources
    from app.adapters.transfers.ftps import FTPSAdapter
    from app.jobs.runner import JobRunner

    class FakeSource:
        async def get_manifest(self, key):
            return [RemoteFileDTO(relative_path="a.mkv", size_bytes=len(DATA))]

    monkeypatch.setattr(sources, "create_source_adapter", lambda *a, **k: FakeSource())
    calls = []

    async def fake_transfer(self, remote_file, remote_base_path, destination_part_path, **kw):
        calls.append(remote_file.relative_path)
        with open(destination_part_path, "wb") as f:
            f.write(DATA)
        return TransferResult(success=True, bytes_transferred=len(DATA), endpoint_name="h")

    monkeypatch.setattr(FTPSAdapter, "transfer_file", fake_transfer)

    async def run():
        return await JobRunner(settings, job_id, "download", "tok").execute()

    async def setup():
        nonlocal job_id
        _, job_id = await _job(settings)
        async with get_session_factory(settings)() as session:
            t = TransferInstance(name="ftp", adapter_type="ftps", config_json={})
            session.add(t)
            await session.flush()
            session.add(TransferEndpoint(transfer_id=t.id, name="p", host="h", port=21, credential_ref=""))
            job = await session.get(Job, job_id)
            job.config_snapshot_json = {**job.config_snapshot_json, "transfer_id": t.id,
                                        "temporary_directory": str(tmp_path)}
            await session.commit()
        return job_id

    job_id = None
    return setup, run, calls, tmp_path / "T" / "a.mkv"


async def _files(settings, job_id):
    async with get_session_factory(settings)() as session:
        return (await session.execute(select(JobFile).where(JobFile.job_id == job_id))).scalars().all()


@pytest.mark.asyncio
async def test_rerun_skips_finished_file_and_keeps_one_row(stage, settings):
    setup, run, calls, final = stage
    job_id = await setup()

    assert (await run()).status == StageRunStatus.SUCCEEDED
    assert final.read_bytes() == DATA and calls == ["a.mkv"]

    assert (await run()).status == StageRunStatus.SUCCEEDED  # e.g. a retry after a later crash
    assert calls == ["a.mkv"]  # not fetched again
    assert len(await _files(settings, job_id)) == 1


@pytest.mark.asyncio
async def test_stale_final_file_is_replaced(stage, settings):
    setup, run, calls, final = stage
    await setup()
    final.parent.mkdir(parents=True)
    final.write_bytes(b"short")  # wrong size: must be re-fetched and overwrite it

    assert (await run()).status == StageRunStatus.SUCCEEDED
    assert calls == ["a.mkv"]
    assert final.read_bytes() == DATA
