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
async def test_update_fetch_without_password_keeps_saved_password(auth_client, app):
    sid = (await auth_client.post("/api/v1/sources", json=_src(fetch=FETCH))).json()["id"]
    no_pw = {k: v for k, v in FETCH.items() if k != "password"}
    r = await auth_client.patch(
        f"/api/v1/sources/{sid}", json={"fetch": {**no_pw, "tls_verify": False}}
    )
    assert r.status_code == 200, r.text
    assert r.json()["fetch"]["tls_verify"] is False
    _, e = await _rows(app)
    cred = json.loads(decrypt_secret(e[0].credential_ref[4:], app.state.master_key))
    assert cred == {"username": "ftpuser", "password": "ftp-secret-pw"}


@pytest.mark.asyncio
async def test_create_fetch_requires_password(auth_client):
    no_pw = {k: v for k, v in FETCH.items() if k != "password"}
    r = await auth_client.post("/api/v1/sources", json=_src(fetch=no_pw))
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


async def _lib_with_history(auth_client, app, with_rule):
    from app.database.models import (
        FileImport,
        Job,
        LibraryInstance,
        MediaMatch,
        SourceItem,
        SourceLabelRule,
    )

    sid = (await auth_client.post("/api/v1/sources", json=_src())).json()["id"]
    async with get_session_factory(app.state.settings)() as s:
        lib = LibraryInstance(
            name="L", adapter_type="sonarr", base_url="http://x", api_key_secret_ref="k"
        )
        s.add(lib)
        await s.flush()
        rule = SourceLabelRule(
            source_id=sid,
            label="x",
            temporary_directory="/t",
            completed_directory="/c",
            library_instance_id=lib.id if with_rule else None,
        )
        item = SourceItem(source_id=sid, remote_id="r")
        s.add_all([rule, item])
        await s.flush()
        job = Job(source_item_id=item.id, rule_id=rule.id, config_snapshot_json={})
        s.add(job)
        await s.flush()
        s.add_all(
            [
                MediaMatch(source_item_id=item.id, library_instance_id=lib.id),
                FileImport(job_id=job.id, candidate_relpath="a", library_instance_id=lib.id),
            ]
        )
        await s.commit()
        return lib.id


@pytest.mark.asyncio
async def test_delete_library_used_by_rule_conflicts(auth_client, app):
    lid = await _lib_with_history(auth_client, app, with_rule=True)
    r = await auth_client.delete(f"/api/v1/libraries/{lid}")
    assert r.status_code == 409
    assert "1 tag mapping" in r.json()["detail"]


@pytest.mark.asyncio
async def test_delete_library_with_only_history_nulls_refs(auth_client, app):
    from app.database.models import FileImport, LibraryInstance, MediaMatch

    lid = await _lib_with_history(auth_client, app, with_rule=False)
    assert (await auth_client.delete(f"/api/v1/libraries/{lid}")).status_code == 204
    async with get_session_factory(app.state.settings)() as s:
        assert await s.get(LibraryInstance, lid) is None
        for m in (MediaMatch, FileImport):
            rows = (await s.execute(select(m))).scalars().all()
            assert len(rows) == 1 and rows[0].library_instance_id is None


@pytest.mark.asyncio
async def test_fetch_test_uses_saved_password_when_blank(auth_client, monkeypatch):
    from app.adapters.transfers.ftps import FTPSAdapter

    seen = {}

    async def fake_test(self):
        seen.update(
            host=self._host,
            port=self._port,
            user=self._username,
            pw=self._password,
            verify=self._tls_verify,
        )
        return {"ok": True, "adapter": "ftps"}

    monkeypatch.setattr(FTPSAdapter, "test_connection", fake_test)
    sid = (await auth_client.post("/api/v1/sources", json=_src(fetch=FETCH))).json()["id"]
    no_pw = {k: v for k, v in FETCH.items() if k != "password"}
    r = await auth_client.post(
        "/api/v1/sources/fetch-test", json={"source_id": sid, **no_pw, "tls_verify": False}
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert seen == {
        "host": "ftp.example",
        "port": 21,
        "user": "ftpuser",
        "pw": "ftp-secret-pw",
        "verify": False,
    }


@pytest.mark.asyncio
async def test_fetch_test_without_any_password_is_rejected(auth_client):
    no_pw = {k: v for k, v in FETCH.items() if k != "password"}
    r = await auth_client.post("/api/v1/sources/fetch-test", json=no_pw)
    assert r.status_code == 422
