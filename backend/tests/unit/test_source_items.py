"""Test source items inventory and queue operations.

Acceptance criteria:
4. First scan inventories completed releases but creates zero automatic Jobs.
11. Source Item remains visible without a Job when label is unmatched/ignored.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_source_items_empty(auth_client):
    """Source items list works when empty."""
    # Need a source first
    r = await auth_client.post(
        "/api/v1/sources",
        json={
            "name": "Test",
            "adapter_type": "rtorrent",
            "connection_config": {},
        },
    )
    source_id = r.json()["id"]

    r = await auth_client.get("/api/v1/source-items")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_source_item_filtered_pagination(auth_client):
    """Source items can be filtered and paginated."""
    r = await auth_client.get("/api/v1/source-items?offset=0&limit=10")
    assert r.status_code == 200
    data = r.json()
    assert data["offset"] == 0
    assert data["limit"] == 10


@pytest.mark.asyncio
async def test_queue_requires_matching_label(auth_client, settings):
    """Queuing a source item without a matching label rule fails."""
    # Create source without labels
    r = await auth_client.post(
        "/api/v1/sources",
        json={
            "name": "Test",
            "adapter_type": "rtorrent",
            "connection_config": {},
        },
    )
    source_id = r.json()["id"]

    # Create a source item directly in DB
    from app.database.session import get_session_factory
    from app.database.models import SourceItem

    factory = get_session_factory(settings)
    async with factory() as session:
        item = SourceItem(
            source_id=source_id,
            remote_id="abc123",
            title="Test.Show.S01E01",
            labels_json=["unknown-label"],
            source_status="completed",
            remote_path="/downloads/Test.Show.S01E01",
            size_bytes=1000,
        )
        session.add(item)
        await session.commit()
        item_id = item.id

    # Try to queue — should fail because no matching label rule
    r = await auth_client.post(
        f"/api/v1/source-items/{item_id}/queue",
        json={
            "force_transfer": False,
        },
    )
    assert r.status_code == 400
    assert "No matching label rule" in r.json()["detail"]


async def _seed(auth_client, settings, specs):
    """specs: (remote_id, eligibility, has_job, ignored). Returns {remote_id: item_id}."""
    from datetime import datetime, timezone

    from app.database.models import Job, SourceItem, SourceLabelRule
    from app.database.session import get_session_factory

    r = await auth_client.post(
        "/api/v1/sources",
        json={
            "name": "Test",
            "adapter_type": "rtorrent",
            "connection_config": {},
        },
    )
    source_id = r.json()["id"]
    ids = {}
    async with get_session_factory(settings)() as session:
        rule = SourceLabelRule(
            source_id=source_id, label="x", temporary_directory="/t", completed_directory="/c"
        )
        session.add(rule)
        await session.flush()
        for remote_id, elig, has_job, ignored in specs:
            item = SourceItem(
                source_id=source_id,
                remote_id=remote_id,
                title=remote_id,
                labels_json=["x"],
                source_status="completed",
                remote_path="/d",
                size_bytes=1,
                last_eligibility=elig,
                ignored_at=datetime.now(timezone.utc) if ignored else None,
            )
            session.add(item)
            await session.flush()
            if has_job:
                session.add(Job(source_item_id=item.id, rule_id=rule.id, config_snapshot_json={}))
            ids[remote_id] = item.id
        await session.commit()
    return ids


@pytest.mark.asyncio
async def test_has_job_false_excludes_items_with_jobs(auth_client, settings):
    ids = await _seed(
        auth_client,
        settings,
        [
            ("a", "already_available", True, False),
            ("b", "already_available", False, False),
        ],
    )
    r = await auth_client.get("/api/v1/source-items?has_job=false")
    assert [i["id"] for i in r.json()["items"]] == [ids["b"]]
    r = await auth_client.get("/api/v1/source-items?has_job=true")
    assert [i["id"] for i in r.json()["items"]] == [ids["a"]]


@pytest.mark.asyncio
async def test_ignored_items_excluded_by_default(auth_client, settings):
    ids = await _seed(
        auth_client,
        settings,
        [
            ("a", "ignored", False, True),
            ("b", "already_available", False, False),
        ],
    )
    r = await auth_client.get("/api/v1/source-items")
    assert [i["id"] for i in r.json()["items"]] == [ids["b"]]
    assert r.json()["total"] == 1
    r = await auth_client.get("/api/v1/source-items?include_ignored=true")
    assert r.json()["total"] == 2


@pytest.mark.asyncio
async def test_skipped_filter_only_already_available(auth_client, settings):
    ids = await _seed(
        auth_client,
        settings,
        [
            ("a", "already_available", False, False),
            ("b", "not_registered", False, False),
            ("c", "needs_review", False, False),
            ("d", "unrouted", False, False),
        ],
    )
    r = await auth_client.get("/api/v1/source-items?eligibility=already_available&has_job=false")
    assert [i["id"] for i in r.json()["items"]] == [ids["a"]]


@pytest.mark.asyncio
async def test_queue_snapshot_has_title_and_list_has_source_name(auth_client, settings):
    ids = await _seed(auth_client, settings, [("a", "missing", False, False)])
    r = await auth_client.get("/api/v1/source-items")
    assert r.json()["items"][0]["source_name"] == "Test"
    r = await auth_client.post(
        f"/api/v1/source-items/{ids['a']}/queue", json={"force_transfer": True}
    )
    assert r.status_code == 200
    from app.database.models import Job
    from app.database.session import get_session_factory

    async with get_session_factory(settings)() as s:
        job = await s.get(Job, r.json()["job_id"])
        assert job.config_snapshot_json["title"] == "a"
        assert job.config_snapshot_json["source_name"] == "Test"


@pytest.mark.asyncio
async def test_delete_source_with_items_and_jobs(auth_client, settings):
    from sqlalchemy import select
    from app.database.models import Job, SourceItem, SourceLabelRule
    from app.database.session import get_session_factory

    await _seed(auth_client, settings, [("a", "missing", True, False)])
    sid = (await auth_client.get("/api/v1/sources")).json()[0]["id"]
    assert (await auth_client.delete(f"/api/v1/sources/{sid}")).status_code == 204
    async with get_session_factory(settings)() as s:
        for m in (Job, SourceItem, SourceLabelRule):
            assert (await s.execute(select(m))).scalars().all() == []
