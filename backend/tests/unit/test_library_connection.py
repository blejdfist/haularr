import httpx
import pytest
import respx
from app.adapters.libraries.radarr import RadarrAdapter
from app.adapters.libraries.sonarr import SonarrAdapter


@pytest.mark.parametrize(
    "adapter_type,expected,other",
    [(SonarrAdapter, "Sonarr", "Radarr"), (RadarrAdapter, "Radarr", "Sonarr")],
)
@pytest.mark.parametrize("identity", ["correct", "wrong", "missing"])
@respx.mock
async def test_connection_verifies_service_identity(adapter_type, expected, other, identity):
    status = {"version": "4.0.0"}
    if identity != "missing":
        status["appName"] = expected if identity == "correct" else other
    respx.get("http://library/api/v3/system/status").mock(
        return_value=httpx.Response(200, json=status)
    )

    result = await adapter_type("lib", "http://library", "key").test_connection()

    assert result["adapter"] == expected.lower()
    if identity == "correct":
        assert result["ok"] is True
        assert result["app_name"] == expected
        assert result["version"] == "4.0.0"
    else:
        assert result["ok"] is False
        assert expected in result["error"]
        assert (other if identity == "wrong" else "unknown service") in result["error"]
