"""Test the /logs endpoint and the in-memory log buffer."""

from __future__ import annotations

import logging

import pytest

from app.logging_buffer import install_log_handler


def _logger(name: str) -> logging.Logger:
    log = logging.getLogger(name)
    log.setLevel(logging.DEBUG)  # emit INFO+ regardless of root level
    return log


@pytest.mark.asyncio
async def test_logs_requires_auth(client):
    """GET /api/v1/logs without a token is rejected."""
    response = await client.get("/api/v1/logs")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_logs_returns_entries_newest_first(auth_client):
    """Authenticated GET returns captured entries, newest first."""
    handler = install_log_handler()
    handler.clear()
    log = _logger("test.logs.basic")
    log.info("hello world")
    log.warning("a warning line")

    response = await auth_client.get("/api/v1/logs")
    assert response.status_code == 200
    data = response.json()
    msgs = [e["message"] for e in data["entries"]]
    assert "a warning line" in msgs
    assert "hello world" in msgs
    # newest first
    assert data["entries"][0]["message"] == "a warning line"
    assert data["capacity"] > 0


@pytest.mark.asyncio
async def test_logs_level_filter(auth_client):
    """The level query param keeps only entries at or above that severity."""
    handler = install_log_handler()
    handler.clear()
    log = _logger("test.logs.level")
    log.info("info line")
    log.error("error line")

    response = await auth_client.get("/api/v1/logs?level=ERROR")
    assert response.status_code == 200
    msgs = [e["message"] for e in response.json()["entries"]]
    assert "error line" in msgs
    assert "info line" not in msgs


@pytest.mark.asyncio
async def test_logs_search_filter(auth_client):
    """The search query param substring-matches message and logger."""
    handler = install_log_handler()
    handler.clear()
    log = _logger("test.logs.search")
    log.info("banana split")
    log.info("chocolate cake")

    response = await auth_client.get("/api/v1/logs?search=banana")
    assert response.status_code == 200
    msgs = [e["message"] for e in response.json()["entries"]]
    assert "banana split" in msgs
    assert "chocolate cake" not in msgs


@pytest.mark.asyncio
async def test_logs_search_matches_logger_name(auth_client):
    """Search also matches against the logger name."""
    handler = install_log_handler()
    handler.clear()
    log = _logger("test.logs.uniqueloggername")
    log.info("ordinary message")
    other = _logger("test.logs.other")
    other.info("other message")

    response = await auth_client.get("/api/v1/logs?search=uniqueloggername")
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["message"] == "ordinary message"


@pytest.mark.asyncio
async def test_logs_limit(auth_client):
    """The limit query param caps the number of returned entries."""
    handler = install_log_handler()
    handler.clear()
    log = _logger("test.logs.limit")
    for i in range(10):
        log.info("line %d", i)

    response = await auth_client.get("/api/v1/logs?limit=3")
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert len(entries) == 3
    # newest first -> last three emitted
    assert entries[0]["message"] == "line 9"
    assert entries[2]["message"] == "line 7"


@pytest.mark.asyncio
async def test_logs_includes_exception_traceback(auth_client):
    """A logged exception includes a formatted traceback in the entry."""
    handler = install_log_handler()
    handler.clear()
    log = _logger("test.logs.exc")

    try:
        raise ValueError("boom")
    except ValueError:
        log.error("something broke", exc_info=True)

    response = await auth_client.get("/api/v1/logs")
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert entries and entries[0]["exception"]
    assert "ValueError: boom" in entries[0]["exception"]
