"""Every API route needs a bearer token, except the ones used to get one and the healthcheck."""

from __future__ import annotations

import pytest

PUBLIC = {
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/setup"),
    ("GET", "/api/v1/auth/setup"),
    ("GET", "/api/v1/health"),
}


@pytest.mark.asyncio
async def test_all_api_routes_require_auth(client):
    spec = (await client.get("/openapi.json")).json()
    routes = [(m.upper(), path) for path, ops in spec["paths"].items() for m in ops]
    assert len(routes) > 30
    for method, path in routes:
        if (method, path) in PUBLIC:
            continue
        url = path.replace("{", "").replace("}", "")  # any value: auth is checked first
        r = await client.request(method, url)
        assert r.status_code == 401, (method, path, r.status_code)


@pytest.mark.asyncio
async def test_openapi_marks_routes_secured(client):
    spec = (await client.get("/openapi.json")).json()
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            assert op.get("description"), (method, path)
            assert op["tags"], (method, path)
            if (method.upper(), path) not in PUBLIC:
                assert op.get("security"), (method, path)
