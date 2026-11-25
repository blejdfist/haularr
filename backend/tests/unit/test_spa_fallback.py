"""The SPA fallback must never serve files outside static_dir."""

from __future__ import annotations

import pytest
from app.main import create_app
from app.settings import Settings
from httpx import ASGITransport, AsyncClient

SECRET = "TOP-SECRET-BODY"


@pytest.fixture
async def spa(tmp_path):
    static = tmp_path / "static"
    (static / "sub").mkdir(parents=True)
    (static / "index.html").write_text("INDEX")
    (static / "sub" / "real.txt").write_text("REAL")
    (tmp_path / "secret").write_text(SECRET)
    s = Settings(config_dir=tmp_path / "cfg", static_dir=static, secret_key="x" * 40)
    async with AsyncClient(transport=ASGITransport(app=create_app(s)), base_url="http://t") as c:
        yield c, tmp_path / "secret"


@pytest.mark.asyncio
async def test_serves_real_file_and_falls_back_to_index(spa):
    client, _ = spa
    assert (await client.get("/sub/real.txt")).text == "REAL"
    assert (await client.get("/some/spa/route")).text == "INDEX"


@pytest.mark.asyncio
async def test_traversal_never_serves_outside_file(spa):
    client, secret = spa
    for url in ("/%2e%2e/secret", "/..%2fsecret", "/" + secret.as_posix()):
        assert (await client.get(url)).text == "INDEX", url


@pytest.mark.asyncio
async def test_unknown_api_path_is_json_404(spa):
    client, _ = spa
    r = await client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}
