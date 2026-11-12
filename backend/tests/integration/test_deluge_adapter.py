"""Test Deluge adapter JSON-RPC with mocked responses."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.adapters.sources.deluge import DelugeAdapter


@pytest.mark.asyncio
async def test_deluge_test_connection_success():
    """Deluge test connection returns ok when auth succeeds."""
    adapter = DelugeAdapter(
        source_id="test",
        web_url="http://deluge.example:8112",
        password="testpass",
    )

    call_count = [0]
    responses = [
        # auth.login -> True
        {"result": True, "error": None, "id": 1},
        # web.connected -> True
        {"result": True, "error": None, "id": 1},
        # core.get_enabled_plugins -> ["Label"]
        {"result": ["Label"], "error": None, "id": 1},
    ]

    async def mock_post(*args, **kwargs):
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1

        class MockResp:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return responses[idx]

        return MockResp()

    with patch("httpx.AsyncClient.post", new=mock_post):
        result = await adapter.test_connection()

    assert result["ok"] is True
    assert result["adapter"] == "deluge"
    assert result["label_plugin_enabled"] is True


@pytest.mark.asyncio
async def test_deluge_test_connection_no_label_plugin():
    """Deluge reports warning when Label plugin not enabled."""
    adapter = DelugeAdapter(
        source_id="test",
        web_url="http://deluge.example:8112",
        password="testpass",
    )

    call_count = [0]
    responses = [
        {"result": True, "error": None, "id": 1},
        {"result": True, "error": None, "id": 1},
        {"result": [], "error": None, "id": 1},  # No plugins
    ]

    async def mock_post(*args, **kwargs):
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1

        class MockResp:
            status_code = 200
            def raise_for_status(self):
                pass
            def json(self):
                return responses[idx]

        return MockResp()

    with patch("httpx.AsyncClient.post", new=mock_post):
        result = await adapter.test_connection()

    assert result["ok"] is True
    assert result["label_plugin_enabled"] is False
    assert "warning" in result
    assert "Label plugin" in result["warning"]
