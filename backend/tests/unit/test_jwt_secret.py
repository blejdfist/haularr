"""JWT secret is generated and persisted when not configured."""

from __future__ import annotations

import pytest
from app.database.models import User
from app.security import create_access_token, get_or_create_jwt_secret
from app.settings import Settings

_USER = User(id="x", password_hash="h")


def test_secret_persisted_and_stable(tmp_path):
    a = get_or_create_jwt_secret(tmp_path)
    assert a == get_or_create_jwt_secret(tmp_path)
    assert len(a) >= 48


def test_empty_secret_fails_closed(tmp_path):
    with pytest.raises(RuntimeError):
        create_access_token(_USER, Settings(config_dir=tmp_path, secret_key=""))


def test_secret_file_is_created_exclusively(tmp_path):
    first = get_or_create_jwt_secret(tmp_path)
    (tmp_path / ".jwt_secret").write_text(first)
    assert get_or_create_jwt_secret(tmp_path) == first


def test_create_private_file_never_overwrites(tmp_path):
    from app.security import _create_private_file

    p = tmp_path / "f"
    assert _create_private_file(p, b"one")
    assert not _create_private_file(p, b"two")
    assert p.read_bytes() == b"one"


def test_master_key_stable_and_race_safe(tmp_path, monkeypatch):
    from app.security import get_or_create_master_key

    key = get_or_create_master_key(tmp_path)
    assert len(key) == 32 and key == get_or_create_master_key(tmp_path)
    # a racing process created the file between our exists() check and our create
    other = tmp_path / "race"
    other.mkdir()
    (other / ".master_key").write_bytes(b"w" * 32)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    assert get_or_create_master_key(other) == b"w" * 32
