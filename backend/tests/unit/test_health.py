"""Test the health endpoint."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """GET /api/v1/health returns healthy status."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database" in data
    assert "version" in data
    from app import __version__

    assert data["version"] == __version__


@pytest.mark.asyncio
async def test_openapi_available(client):
    """OpenAPI schema is generated."""
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert "paths" in data
