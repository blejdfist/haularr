"""Test Sonarr and Radarr library adapter DTO parsing with mocked HTTP."""

from __future__ import annotations

from datetime import UTC
from unittest.mock import AsyncMock, patch

import pytest
from app.adapters.libraries.radarr import RadarrAdapter
from app.adapters.libraries.sonarr import SonarrAdapter
from app.domain.models import MediaType


@pytest.mark.asyncio
async def test_sonarr_parse_not_registered():
    """Sonarr parse returns catalog_id=None when series not registered."""
    adapter = SonarrAdapter(
        library_id="test",
        base_url="http://sonarr:8989",
        api_key="test-key",
    )

    # Parse returns a series object without ID
    mock_response = {
        "series": None,
        "parsedEpisodeInfo": {"seriesTitle": "Unknown Show"},
    }

    mock = type(
        "MockResp",
        (),
        {
            "json": lambda self: mock_response,
            "raise_for_status": lambda self: None,
        },
    )()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock):
        result = await adapter.parse("Unknown.Show.S01E01.1080p")

    assert result.media_type == MediaType.SERIES
    assert result.catalog_id is None
    assert result.confidence < 0.5


@pytest.mark.asyncio
async def test_sonarr_parse_registered():
    """Sonarr parse returns catalog_id when series is registered."""
    adapter = SonarrAdapter(
        library_id="test",
        base_url="http://sonarr:8989",
        api_key="test-key",
    )

    mock_response = {
        "series": {"id": 42, "title": "Test Show", "year": 2020},
        "episodes": [{"id": 1}, {"id": 2}],
        "parsedEpisodeInfo": {"seriesTitle": "Test Show", "seasonNumber": 1},
    }

    mock = type(
        "MockResp",
        (),
        {
            "json": lambda self: mock_response,
            "raise_for_status": lambda self: None,
        },
    )()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock):
        result = await adapter.parse("Test.Show.S01E01.1080p")

    assert result.media_type == MediaType.SERIES
    assert result.catalog_id == 42
    assert result.episode_ids == [1, 2]
    assert result.confidence >= 0.8


@pytest.mark.asyncio
async def test_radarr_parse_registered():
    """Radarr parse returns catalog_id when movie is registered."""
    adapter = RadarrAdapter(
        library_id="test",
        base_url="http://radarr:7878",
        api_key="test-key",
    )

    mock_response = {
        "movie": {"id": 10, "title": "Test Movie", "year": 2023},
        "parsedMovieInfo": {"movieTitle": "Test Movie", "year": 2023},
    }

    mock = type(
        "MockResp",
        (),
        {
            "json": lambda self: mock_response,
            "raise_for_status": lambda self: None,
        },
    )()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock):
        result = await adapter.parse("Test.Movie.2023.1080p")

    assert result.media_type == MediaType.MOVIE
    assert result.catalog_id == 10
    assert result.confidence >= 0.8


@pytest.mark.asyncio
async def test_sonarr_inspect_library_uses_parse_hasfile():
    """inspect_library derives missing episodes from parse data, no HTTP."""
    from app.domain.models import MediaMatch

    adapter = SonarrAdapter(library_id="test", base_url="http://sonarr:8989", api_key="k")
    match = MediaMatch(
        media_type=MediaType.SERIES,
        catalog_id=42,
        title="Test Show",
        episode_ids=[1, 2],
        library_record={"episodes": [{"id": 1, "hasFile": True}, {"id": 2, "hasFile": False}]},
    )
    get = AsyncMock()
    with patch("httpx.AsyncClient.get", get):
        inv = await adapter.inspect_library(match)

    assert inv.missing_episode_ids == [2]
    assert inv.has_file is True
    assert inv.registered is True
    get.assert_not_called()


@pytest.mark.asyncio
async def test_radarr_inspect_library_uses_parse_movie():
    from app.domain.models import MediaMatch

    adapter = RadarrAdapter(library_id="test", base_url="http://radarr:7878", api_key="k")
    match = MediaMatch(
        media_type=MediaType.MOVIE,
        catalog_id=5,
        title="Test Movie",
        library_record={
            "movie": {
                "id": 5,
                "hasFile": True,
                "movieFile": {"quality": {"quality": {"name": "Bluray-1080p"}}},
            }
        },
    )
    get = AsyncMock()
    with patch("httpx.AsyncClient.get", get):
        inv = await adapter.inspect_library(match)

    assert inv.has_file is True
    assert inv.existing_quality == "Bluray-1080p"
    get.assert_not_called()


def _resp(data):
    return type(
        "MockResp", (), {"json": lambda self: data, "raise_for_status": lambda self: None}
    )()


@pytest.mark.asyncio
async def test_radarr_inspect_import_without_match_takes_each_files_movie():
    """Skipped library check: no expected movie, so Radarr's own per-file match decides."""
    from app.domain.models import MediaMatch

    adapter = RadarrAdapter(library_id="test", base_url="http://radarr:7878", api_key="k")
    rows = [
        {"path": "/c/Tron/Tron.1982.mkv", "movie": {"id": 1}, "rejections": []},
        {"path": "/c/Tron/Tron.Legacy.2010.mkv", "movie": {"id": 2}, "rejections": []},
        {"path": "/c/Tron/sample.mkv", "movie": None, "rejections": []},
    ]
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=_resp(rows)):
        inspection = await adapter.inspect_import("/c/Tron", MediaMatch(media_type=MediaType.MOVIE))

    ok = {c.absolute_path: c.media_id for c in inspection.candidates if not c.rejection_reasons}
    assert ok == {"/c/Tron/Tron.1982.mkv": 1, "/c/Tron/Tron.Legacy.2010.mkv": 2}
    assert not inspection.all_rejected


@pytest.mark.asyncio
async def test_sonarr_inspect_import_without_match_takes_each_files_series():
    from app.domain.models import MediaMatch

    adapter = SonarrAdapter(library_id="test", base_url="http://sonarr:8989", api_key="k")
    rows = [
        {"path": "/c/P/a.mkv", "series": {"id": 7}, "episodes": [{"id": 70}], "rejections": []},
        {"path": "/c/P/b.mkv", "series": None, "episodes": [], "rejections": []},
    ]
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=_resp(rows)):
        inspection = await adapter.inspect_import("/c/P", MediaMatch(media_type=MediaType.SERIES))

    ok = [(c.media_id, c.episode_ids) for c in inspection.candidates if not c.rejection_reasons]
    assert ok == [(7, [70])]


@pytest.mark.asyncio
async def test_radarr_reconcile_without_match_checks_each_imported_movie():
    from datetime import datetime

    from app.domain.models import ImportOperation, MediaMatch

    adapter = RadarrAdapter(library_id="test", base_url="http://radarr:7878", api_key="k")
    op = ImportOperation(
        operation_id="9",
        command_id=9,
        submitted_at=datetime.now(UTC),
        candidates=["/a.mkv", "/b.mkv"],
        media_ids=[1, 2],
    )
    replies = {
        "/api/v3/command/9": {"status": "completed"},
        "/api/v3/movie/1": {"hasFile": True},
        "/api/v3/movie/2": {"hasFile": False},
    }

    async def get(self, url, params=None):
        return _resp(replies[url])

    with patch("httpx.AsyncClient.get", get):
        outcome = await adapter.reconcile_import(op, MediaMatch(media_type=MediaType.MOVIE))
    assert not outcome.success
    assert "2" in outcome.details["error"]
