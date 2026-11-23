from __future__ import annotations

import pytest


@pytest.fixture
def fake_adapter(monkeypatch):
    seen: dict = {}

    class Fake:
        async def test_connection(self):
            return {"ok": True}

    def factory(library_id, adapter_type, base_url, api_key, options=None):
        seen["api_key"] = api_key
        seen["base_url"] = base_url
        return Fake()

    import app.adapters.libraries as libs
    monkeypatch.setattr(libs, "create_library_adapter", factory)
    return seen


@pytest.mark.asyncio
async def test_test_config_uses_given_key(auth_client, fake_adapter):
    r = await auth_client.post("/api/v1/libraries/test-config", json={
        "adapter_type": "sonarr", "base_url": "http://s:8989", "api_key": "abc",
    })
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert fake_adapter["api_key"] == "abc"


@pytest.mark.asyncio
async def test_test_config_falls_back_to_stored_key(auth_client, fake_adapter):
    lib = (await auth_client.post("/api/v1/libraries", json={
        "name": "S", "adapter_type": "sonarr", "base_url": "http://s:8989",
        "api_key_secret_ref": "stored",
    })).json()
    r = await auth_client.post("/api/v1/libraries/test-config", json={
        "adapter_type": "sonarr", "base_url": "http://new:8989", "api_key": "",
        "library_id": lib["id"],
    })
    assert r.status_code == 200
    assert fake_adapter["api_key"] == "stored"
    assert fake_adapter["base_url"] == "http://new:8989"


@pytest.mark.asyncio
async def test_test_config_requires_key(auth_client, fake_adapter):
    r = await auth_client.post("/api/v1/libraries/test-config", json={
        "adapter_type": "sonarr", "base_url": "http://s:8989",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_test_config_rejects_unknown_type(auth_client, fake_adapter):
    r = await auth_client.post("/api/v1/libraries/test-config", json={
        "adapter_type": "lidarr", "base_url": "http://s", "api_key": "k",
    })
    assert r.status_code == 422
