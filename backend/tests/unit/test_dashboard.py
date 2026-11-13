"""Test dashboard endpoint returns comprehensive data."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_dashboard_empty(client):
    """Dashboard returns valid structure when empty."""
    r = await client.get("/api/v1/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert "jobs" in data
    assert "sources" in data
    assert "source_items_total" in data
    assert "capacity" in data
    assert "disk" in data
    assert "recent_jobs" in data

    # Check job counts structure
    jobs = data["jobs"]
    assert "active" in jobs
    assert "queued" in jobs
    assert "running" in jobs
    assert "completed" in jobs
    assert "needs_attention" in jobs
    assert "completed_today" in jobs

    # Disk info
    assert isinstance(data["disk"], dict)
