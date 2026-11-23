"""Source-owned FTP fetch config."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.database.models import TransferEndpoint, TransferInstance
from app.database.session import get_session_factory
from app.security import decrypt_secret

FETCH = {
    "host": "ftp.example",
    "port": 21,
    "username": "ftpuser",
    "password": "ftp-secret-pw",
    "path_mappings": [{"source_prefix": "/dl", "remote_prefix": "/home/dl"}],
}


def _src(**kw):
    return {
        "name": "Box",
        "adapter_type": "rtorrent",
        "connection_config": {"xmlrpc_url": "https://x/RPC2"},
        "credential": "rt-secret-pw",
        **kw,
    }


async def _rows(app):
    async with get_session_factory(app.state.settings)() as s:
        t = (await s.execute(select(TransferInstance))).scalars().all()
        e = (await s.execute(select(TransferEndpoint))).scalars().all()
        return t, e


@pytest.mark.asyncio
async def test_create_source_with_fetch_creates_transfer(auth_client):
    r = await auth_client.post("/api/v1/sources", json=_src(fetch=FETCH))
    assert r.status_code == 201, r.text
    g = await auth_client.get(f"/api/v1/sources/{r.json()['id']}")
    assert g.json()["fetch"]["host"] == "ftp.example"
    assert g.json()["fetch"]["has_password"] is True
    for text in (r.text, g.text):
        assert "ftp-secret-pw" not in text and "rt-secret-pw" not in text


@pytest.mark.asyncio
async def test_update_fetch_replaces_endpoint(auth_client, app):
    sid = (await auth_client.post("/api/v1/sources", json=_src(fetch=FETCH))).json()["id"]
    new = {**FETCH, "host": "new.example", "username": "u2", "password": "pw2"}
    r = await auth_client.patch(f"/api/v1/sources/{sid}", json={"fetch": new})
    assert r.status_code == 200, r.text
    f = (await auth_client.get(f"/api/v1/sources/{sid}")).json()["fetch"]
    assert f["host"] == "new.example" and f["username"] == "u2"
    t, e = await _rows(app)
    assert len(t) == 1 and len(e) == 1
    cred = json.loads(decrypt_secret(e[0].credential_ref[4:], app.state.master_key))
    assert cred == {"username": "u2", "password": "pw2"}


@pytest.mark.asyncio
async def test_update_fetch_requires_password(auth_client):
    sid = (await auth_client.post("/api/v1/sources", json=_src(fetch=FETCH))).json()["id"]
    bad = {k: v for k, v in FETCH.items() if k != "password"}
    r = await auth_client.patch(f"/api/v1/sources/{sid}", json={"fetch": bad})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_without_fetch_leaves_transfer(auth_client, app):
    sid = (await auth_client.post("/api/v1/sources", json=_src(fetch=FETCH))).json()["id"]
    _, before = await _rows(app)
    snap = (before[0].host, before[0].credential_ref, before[0].path_mappings_json)
    r = await auth_client.patch(f"/api/v1/sources/{sid}", json={"name": "Renamed"})
    assert r.status_code == 200
    _, after = await _rows(app)
    assert len(after) == 1
    assert (after[0].host, after[0].credential_ref, after[0].path_mappings_json) == snap


@pytest.mark.asyncio
async def test_update_without_credential_keeps_source_credential(auth_client, app):
    from app.database.models import SourceInstance

    sid = (await auth_client.post("/api/v1/sources", json=_src())).json()["id"]

    async def ref():
        async with get_session_factory(app.state.settings)() as s:
            return (await s.get(SourceInstance, sid)).credential_ref

    before = await ref()
    r = await auth_client.patch(f"/api/v1/sources/{sid}", json={"name": "Renamed"})
    assert r.json()["has_credential"] is True
    assert await ref() == before


@pytest.mark.asyncio
async def test_delete_source_removes_owned_transfer(auth_client, app):
    sid = (await auth_client.post("/api/v1/sources", json=_src(fetch=FETCH))).json()["id"]
    assert (await auth_client.delete(f"/api/v1/sources/{sid}")).status_code == 204
    t, e = await _rows(app)
    assert t == [] and e == []
