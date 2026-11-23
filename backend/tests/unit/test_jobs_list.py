"""Jobs list: multi-status filter, attention sort, title and library name."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database.models import Job, LibraryInstance, SourceItem
from app.database.repositories import LabelRuleRepository, SourceRepository
from app.database.session import get_session_factory


async def _seed(settings, specs, library_id="lib-1"):
    """specs: list of (status, age_minutes). Returns title and library name."""
    factory = get_session_factory(settings)
    now = datetime.now(timezone.utc)
    async with factory() as session:
        source = await SourceRepository(session).create(
            name="S", adapter_type="rtorrent", connection_config_json={}, credential_ref=""
        )
        rule = await LabelRuleRepository(session).create(
            source_id=source.id, label="tv", temporary_directory="/t", completed_directory="/c"
        )
        session.add(LibraryInstance(
            id="lib-1", name="My Sonarr", adapter_type="sonarr", base_url="http://x",
            api_key_secret_ref="",
        ))
        for n, (status, age) in enumerate(specs):
            item = SourceItem(
                source_id=source.id, remote_id=f"h{n}", title=f"Title {n}",
                labels_json=["tv"], source_status="completed", remote_path="/p", size_bytes=1,
            )
            session.add(item)
            await session.flush()
            snap = {"library_instance_id": library_id} if library_id else {}
            session.add(Job(
                source_item_id=item.id, rule_id=rule.id, config_snapshot_json=snap,
                status=status, created_at=now - timedelta(minutes=age),
            ))
        await session.commit()


@pytest.mark.asyncio
async def test_status_accepts_comma_list(auth_client, settings):
    await _seed(settings, [("failed", 3), ("running", 2), ("completed", 1)])
    r = await auth_client.get("/api/v1/jobs?status=failed,running")
    assert r.status_code == 200
    assert {i["status"] for i in r.json()["items"]} == {"failed", "running"}
    assert r.json()["total"] == 2


@pytest.mark.asyncio
async def test_sort_attention_puts_failed_first(auth_client, settings):
    await _seed(settings, [("needs_attention", 10), ("completed", 1)])
    r = await auth_client.get("/api/v1/jobs?sort=attention")
    assert r.json()["items"][0]["status"] == "needs_attention"
    r = await auth_client.get("/api/v1/jobs")
    assert r.json()["items"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_list_includes_title_and_library_name(auth_client, settings):
    await _seed(settings, [("queued", 1)])
    item = (await auth_client.get("/api/v1/jobs")).json()["items"][0]
    assert item["title"] == "Title 0"
    assert item["library_name"] == "My Sonarr"


@pytest.mark.asyncio
async def test_list_library_name_null_when_library_missing(auth_client, settings):
    await _seed(settings, [("queued", 1)], library_id=None)
    r = await auth_client.get("/api/v1/jobs")
    assert r.status_code == 200
    assert r.json()["items"][0]["library_name"] is None
