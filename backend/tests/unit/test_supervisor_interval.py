"""Poll loop: fast progress-only ticks while a torrent downloads, full scans on the source's interval."""

from __future__ import annotations

import asyncio

from app.database.models import Job, SourceItem
from app.database.repositories import LabelRuleRepository, SourceRepository
from app.database.session import get_session_factory


async def _source(settings, job_status: str | None) -> str:
    async with get_session_factory(settings)() as session:
        src = await SourceRepository(session).create(
            name="S",
            adapter_type="rtorrent",
            connection_config_json={},
            credential_ref="",
            poll_interval=30,
        )
        rule = await LabelRuleRepository(session).create(
            source_id=src.id, label="tv", temporary_directory="/t", completed_directory="/c"
        )
        item = SourceItem(source_id=src.id, remote_id="h", title="T", labels_json=["tv"])
        session.add(item)
        await session.flush()
        if job_status:
            session.add(
                Job(
                    source_item_id=item.id,
                    rule_id=rule.id,
                    config_snapshot_json={},
                    stage="source_download",
                    status=job_status,
                )
            )
        await session.commit()
        return src.id


async def _ticks(settings, monkeypatch, job_status, n=8):
    """Run the poll loop for ``n`` sleeps on a fake clock; return [(progress_only, slept)]."""
    from app.jobs import supervisor as sup
    from app.services.discovery import DiscoveryService

    source_id = await _source(settings, job_status)
    clock = [0.0]
    log: list[list] = []

    async def fake_scan(self, sid, progress_only=False):
        log.append([progress_only, None])

    async def fake_sleep(s):
        log[-1][1] = s
        clock[0] += s
        if len(log) >= n:
            raise asyncio.CancelledError

    monkeypatch.setattr(DiscoveryService, "run_discovery_for_source", fake_scan)
    monkeypatch.setattr(sup.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(sup.asyncio, "sleep", fake_sleep)
    s = sup.DiscoverySupervisor(settings, b"k")
    s._running = True
    await s._source_poll_loop(source_id, 30, "S")
    return [tuple(x) for x in log]


async def test_downloading_polls_fast_but_scans_library_on_interval(app, settings, monkeypatch):
    ticks = await _ticks(settings, monkeypatch, "waiting_source")
    assert all(slept == 5 for _, slept in ticks)
    # Full scan at t=0 and t=30; progress-only in between.
    assert [p for p, _ in ticks] == [False, True, True, True, True, True, False, True]


async def test_idle_source_polls_on_interval(app, settings, monkeypatch):
    ticks = await _ticks(settings, monkeypatch, "needs_attention", n=3)
    assert ticks == [(False, 30), (False, 30), (False, 30)]
