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
    r = await auth_client.post("/api/v1/sources", json={
        "name": "Test",
        "adapter_type": "rtorrent",
        "connection_secret_ref": "{}",
    })
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
    r = await auth_client.post("/api/v1/sources", json={
        "name": "Test",
        "adapter_type": "rtorrent",
        "connection_secret_ref": "{}",
    })
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
    r = await auth_client.post(f"/api/v1/source-items/{item_id}/queue", json={
        "force_transfer": False,
    })
    assert r.status_code == 400
    assert "No matching label rule" in r.json()["detail"]
