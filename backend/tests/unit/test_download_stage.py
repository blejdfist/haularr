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
    """A download job for item 'T'; remote files are ``names`` (default one 10-byte a.mkv).

    Downloads land in tmp/in, publish moves to tmp/done."""
    from app.adapters import sources
    from app.adapters.transfers.ftps import FTPSAdapter
    from app.jobs.runner import JobRunner

    class FakeSource:
        async def get_manifest(self, key):
            return [RemoteFileDTO(relative_path=n, size_bytes=len(DATA)) for n in names]

    monkeypatch.setattr(sources, "create_source_adapter", lambda *a, **k: FakeSource())
    calls = []
    names = ["a.mkv"]

    async def fake_transfer(self, remote_file, remote_base_path, destination_part_path, **kw):
        calls.append(remote_file.relative_path)
        with open(destination_part_path, "wb") as f:
            f.write(DATA)
        return TransferResult(success=True, bytes_transferred=len(DATA), endpoint_name="h")

    monkeypatch.setattr(FTPSAdapter, "transfer_file", fake_transfer)

    async def run(stage="transfer"):
        return await JobRunner(settings, job_id, stage, "tok").execute()

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
                                        "title": "T", "temporary_directory": str(tmp_path / "in"),
                                        "completed_directory": str(tmp_path / "done")}
            await session.commit()
        return job_id

    job_id = None
    return setup, run, calls, tmp_path / "in" / "T" / "a.mkv", names


async def _files(settings, job_id):
    async with get_session_factory(settings)() as session:
        return (await session.execute(select(JobFile).where(JobFile.job_id == job_id))).scalars().all()


@pytest.mark.asyncio
async def test_rerun_skips_finished_file_and_keeps_one_row(stage, settings):
    setup, run, calls, final, _ = stage
    job_id = await setup()

    assert (await run()).status == StageRunStatus.SUCCEEDED
    assert final.read_bytes() == DATA and calls == ["a.mkv"]

    assert (await run()).status == StageRunStatus.SUCCEEDED  # e.g. a retry after a later crash
    assert calls == ["a.mkv"]  # not fetched again
    assert len(await _files(settings, job_id)) == 1


@pytest.mark.asyncio
async def test_stale_final_file_is_replaced(stage, settings):
    setup, run, calls, final, _ = stage
    await setup()
    final.parent.mkdir(parents=True)
    final.write_bytes(b"short")  # wrong size: must be re-fetched and overwrite it

    assert (await run()).status == StageRunStatus.SUCCEEDED
    assert calls == ["a.mkv"]
    assert final.read_bytes() == DATA


async def _pipeline(run):
    for st in ("transfer", "verify", "extract", "move"):
        r = await run(st)
        assert r.status in (StageRunStatus.SUCCEEDED, StageRunStatus.SKIPPED), (st, r)


@pytest.mark.asyncio
async def test_single_file_release_downloads_flat_and_moves(stage, tmp_path):
    setup, run, calls, _, names = stage
    names[:] = ["T"]  # single-file torrent: the file is named like the item
    await setup()
    await _pipeline(run)
    assert (tmp_path / "done" / "T").read_bytes() == DATA  # a file, no extra folder
    assert not (tmp_path / "in" / "T").exists()


@pytest.mark.asyncio
async def test_folder_release_moves_whole_folder(stage, tmp_path):
    setup, run, calls, _, names = stage
    names[:] = ["a.mkv", "Subs/en.srt"]
    await setup()
    await _pipeline(run)
    assert (tmp_path / "done" / "T" / "a.mkv").read_bytes() == DATA
    assert (tmp_path / "done" / "T" / "Subs" / "en.srt").exists()
    assert not (tmp_path / "in" / "T").exists()


@pytest.mark.asyncio
async def test_rar_release_extracts_in_place_and_moves_only_extracted(stage, tmp_path, monkeypatch):
    from app.processing import extraction
    from app.processing.extraction import ExtractionResult

    def fake_extract(archive, dest):
        assert dest == archive.parent  # in place, no extra folder
        (dest / "ep.mkv").write_bytes(b"video")
        return ExtractionResult(success=True, extracted_files=["ep.mkv"])

    monkeypatch.setattr(extraction, "extract_archive", fake_extract)
    setup, run, calls, _, names = stage
    names[:] = ["t.rar", "t.r00", "t.nfo"]
    await setup()
    await _pipeline(run)
    assert sorted(p.name for p in (tmp_path / "done" / "T").iterdir()) == ["ep.mkv"]
    assert (tmp_path / "in" / "T" / "t.rar").exists()  # left for cleanup


@pytest.mark.asyncio
async def test_extract_records_byte_progress(stage, settings, monkeypatch):
    from app.database.models import StageRun
    from app.processing import extraction
    from app.processing.extraction import ExtractionResult

    def fake_extract(archive, dest):
        (dest / "ep.mkv").write_bytes(b"video")
        return ExtractionResult(success=True, extracted_files=["ep.mkv"])

    monkeypatch.setattr(extraction, "extract_archive", fake_extract)
    setup, run, _, _, names = stage
    names[:] = ["t.rar", "t.r00"]
    job_id = await setup()
    for st in ("transfer", "verify", "extract"):
        await run(st)
    async with get_session_factory(settings)() as session:
        run_row = (await session.execute(
            select(StageRun).where(StageRun.job_id == job_id, StageRun.stage == "extract")
        )).scalars().one()
    assert run_row.progress_json["bytes_total"] == 2 * len(DATA)
    assert run_row.progress_json["bytes_done"] == run_row.progress_json["bytes_total"]
    assert run_row.progress_json["extracted"] == ["ep.mkv"]


@pytest.mark.asyncio
async def test_every_expected_file_is_listed_with_its_own_status(stage, settings, monkeypatch):
    from app.adapters.transfers.ftps import FTPSAdapter

    setup, run, _, _, names = stage
    names[:] = ["a.mkv", "b.mkv", "c.mkv"]
    job_id = await setup()
    seen_during_a = {}

    async def transfer(self, remote_file, remote_base_path, destination_part_path, **kw):
        if remote_file.relative_path == "a.mkv":
            seen_during_a.update({f.remote_relpath: f.transfer_status for f in await _files(settings, job_id)})
            with open(destination_part_path, "wb") as f:
                f.write(DATA)
            return TransferResult(success=True, bytes_transferred=len(DATA), endpoint_name="h")
        return TransferResult(success=False, bytes_transferred=0, endpoint_name="h", error="boom")

    monkeypatch.setattr(FTPSAdapter, "transfer_file", transfer)
    assert (await run()).status == StageRunStatus.FAILED

    # All files exist before the first transfer finishes; the active one is marked.
    assert seen_during_a == {"a.mkv": "in_progress", "b.mkv": "pending", "c.mkv": "pending"}
    after = {f.remote_relpath: f.transfer_status for f in await _files(settings, job_id)}
    assert after == {"a.mkv": "completed", "b.mkv": "failed", "c.mkv": "pending"}
