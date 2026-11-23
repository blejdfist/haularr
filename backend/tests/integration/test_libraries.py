"""Test Sonarr and Radarr library adapter DTO parsing with mocked HTTP."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.adapters.libraries.sonarr import SonarrAdapter
from app.adapters.libraries.radarr import RadarrAdapter
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

    mock = type("MockResp", (), {
        "json": lambda self: mock_response,
        "raise_for_status": lambda self: None,
    })()

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

    mock = type("MockResp", (), {
        "json": lambda self: mock_response,
        "raise_for_status": lambda self: None,
    })()

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

    mock = type("MockResp", (), {
        "json": lambda self: mock_response,
        "raise_for_status": lambda self: None,
    })()

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
