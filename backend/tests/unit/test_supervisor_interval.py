"""Sources poll faster while one of their torrents is downloading, so progress looks live."""

from __future__ import annotations

from app.database.models import Job, SourceItem
from app.database.repositories import LabelRuleRepository, SourceRepository
from app.database.session import get_session_factory


async def _source(settings, job_status: str | None) -> str:
    async with get_session_factory(settings)() as session:
        src = await SourceRepository(session).create(
            name="S", adapter_type="rtorrent", connection_config_json={}, credential_ref="", poll_interval=30
        )
        rule = await LabelRuleRepository(session).create(
            source_id=src.id, label="tv", temporary_directory="/t", completed_directory="/c"
        )
        item = SourceItem(source_id=src.id, remote_id="h", title="T", labels_json=["tv"])
        session.add(item)
        await session.flush()
        if job_status:
            session.add(Job(source_item_id=item.id, rule_id=rule.id, config_snapshot_json={},
                            stage="source_download", status=job_status))
        await session.commit()
        return src.id


async def test_poll_interval_drops_to_5s_while_downloading(app, settings):
    from app.jobs.supervisor import DiscoverySupervisor

    source_id = await _source(settings, "waiting_source")
    assert await DiscoverySupervisor(settings, b"k")._get_poll_interval(source_id) == 5


async def test_poll_interval_normal_when_idle(app, settings):
    from app.jobs.supervisor import DiscoverySupervisor

    source_id = await _source(settings, "needs_attention")
    assert await DiscoverySupervisor(settings, b"k")._get_poll_interval(source_id) == 30
