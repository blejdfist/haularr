import httpx
import pytest
import respx
from app.adapters.libraries.sonarr import SonarrAdapter


@pytest.mark.asyncio
@respx.mock
async def test_sonarr_test_connection_uses_api_v3():
    route = respx.get("http://sonarr:8989/api/v3/system/status").mock(
        return_value=httpx.Response(200, json={"version": "4.0.0", "appName": "Sonarr"})
    )
    result = await SonarrAdapter("lib", "http://sonarr:8989/", "key").test_connection()
    assert route.called
    assert result["ok"] is True
    assert result["version"] == "4.0.0"
