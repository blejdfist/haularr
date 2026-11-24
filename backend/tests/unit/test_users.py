"""Users live in the database: setup once, login by password, tokens die with the user."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import delete

from app.database.models import User
from app.database.session import get_session_factory


@pytest.mark.asyncio
async def test_setup_login_and_deleted_user(client, settings):
    creds = {"username": "jim", "password": "pw"}
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 400  # no users yet

    r = await client.post("/api/v1/auth/setup", json=creds)
    assert r.status_code == 200
    assert (await client.post("/api/v1/auth/setup", json=creds)).status_code == 409

    assert (await client.post("/api/v1/auth/login", json={**creds, "password": "no"})).status_code == 401
    token = (await client.post("/api/v1/auth/login", json=creds)).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/settings", headers=auth)).status_code == 200

    async with get_session_factory(settings)() as s:
        await s.execute(delete(User))
        await s.commit()
    assert (await client.get("/api/v1/settings", headers=auth)).status_code == 401


def test_migration_imports_legacy_admin_env(tmp_path, monkeypatch):
    from alembic import command

    from app.main import _alembic_config
    from app.settings import Settings

    monkeypatch.setenv("HAULARR_CONFIG_DIR", str(tmp_path))
    (tmp_path / ".admin.env").write_text(
        "HAULARR_ADMIN_USERNAME=jim\nHAULARR_ADMIN_PASSWORD_HASH=$2b$12$abc\n", encoding="utf-8"
    )
    command.upgrade(_alembic_config(Settings(config_dir=tmp_path)), "head")
    rows = sqlite3.connect(tmp_path / "haularr.db").execute(
        "select username, password_hash, is_admin from users"
    ).fetchall()
    assert rows == [("jim", "$2b$12$abc", 1)]
