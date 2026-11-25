"""Test dashboard endpoint returns comprehensive data."""

from __future__ import annotations

from datetime import UTC

import pytest


@pytest.mark.asyncio
async def test_dashboard_empty(auth_client):
    """Dashboard returns valid structure when empty."""
    r = await auth_client.get("/api/v1/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert "jobs" in data
    assert "sources" in data
    assert "source_items_total" in data
    assert "recent_jobs" in data

    # Check job counts structure
    jobs = data["jobs"]
    assert "queued" in jobs
    assert "running" in jobs
    assert "completed" in jobs
    assert "needs_attention" in jobs
    assert "completed_today" in jobs


async def _seed(settings, specs, error=None):
    """specs: [(status, ended_days_ago|None)]; also creates a source with last_scan_error."""
    from datetime import datetime, timedelta

    from app.database.models import Job, SourceInstance, SourceItem, SourceLabelRule
    from app.database.session import get_session_factory

    now = datetime.now(UTC)
    async with get_session_factory(settings)() as session:
        src = SourceInstance(
            name="Src",
            adapter_type="rtorrent",
            connection_config_json={},
            credential_ref="",
            last_scan_error=error,
        )
        session.add(src)
        await session.flush()
        rule = SourceLabelRule(
            source_id=src.id, label="tv", temporary_directory="/t", completed_directory="/c"
        )
        session.add(rule)
        for n, (status, days) in enumerate(specs):
            item = SourceItem(
                source_id=src.id,
                remote_id=f"h{n}",
                title=f"T{n}",
                labels_json=["tv"],
                source_status="completed",
                remote_path="/p",
                size_bytes=1,
            )
            session.add(item)
            await session.flush()
            session.add(
                Job(
                    source_item_id=item.id,
                    rule_id=rule.id,
                    config_snapshot_json={},
                    status=status,
                    ended_at=now - timedelta(days=days) if days is not None else None,
                )
            )
        await session.commit()
        return src.id


@pytest.mark.asyncio
async def test_dashboard_completed_7d(auth_client, settings):
    await _seed(settings, [("completed", 2), ("completed", 10), ("completed_with_warnings", 1)])
    jobs = (await auth_client.get("/api/v1/dashboard")).json()["jobs"]
    assert jobs["completed_7d"] == 2


@pytest.mark.asyncio
async def test_dashboard_by_status(auth_client, settings):
    await _seed(settings, [("queued", None), ("waiting_source", None)])
    assert (await auth_client.get("/api/v1/dashboard")).json()["jobs"]["by_status"] == {
        "queued": 1,
        "waiting_source": 1,
    }


@pytest.mark.asyncio
async def test_dashboard_source_health(auth_client, settings):
    sid = await _seed(settings, [], error="boom")
    health = (await auth_client.get("/api/v1/dashboard")).json()["source_health"]
    assert next(h for h in health if h["id"] == sid)["last_scan_error"] == "boom"
