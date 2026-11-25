"""Server folder browsing uses the server filesystem and requires authentication."""

from pathlib import Path

import pytest


async def test_listing_directories(auth_client, tmp_path):
    tmp_path = tmp_path / "browse"
    tmp_path.mkdir()
    for name in ["Zulu", "alpha", "日本語", ".hidden"]:
        (tmp_path / name).mkdir()
    (tmp_path / "file.txt").write_text("not a directory")
    response = await auth_client.get("/api/v1/filesystem", params={"path": str(tmp_path)})
    assert response.status_code == 200
    data = response.json()
    assert data["path"] == str(tmp_path.resolve())
    assert data["parent"] == str(tmp_path.resolve().parent)
    assert [entry["name"] for entry in data["directories"]] == [
        ".hidden",
        "alpha",
        "Zulu",
        "日本語",
    ]
    assert all(Path(entry["path"]).is_dir() for entry in data["directories"])


async def test_roots(auth_client):
    response = await auth_client.get("/api/v1/filesystem")
    assert response.status_code == 200
    data = response.json()
    assert data["path"] is None
    assert data["parent"] is None
    assert data["directories"]
    root = data["directories"][0]["path"]
    response = await auth_client.get("/api/v1/filesystem", params={"path": root})
    assert response.status_code == 200
    assert response.json()["parent"] is None


@pytest.mark.parametrize("kind,status", [("missing", 404), ("file", 400)])
async def test_invalid_location(auth_client, tmp_path, kind, status):
    target = tmp_path / kind
    if kind == "file":
        target.write_text("test")
    response = await auth_client.get("/api/v1/filesystem", params={"path": str(target)})
    assert response.status_code == status


async def test_relative_path_rejected(auth_client):
    response = await auth_client.get("/api/v1/filesystem", params={"path": "relative"})
    assert response.status_code == 400


async def test_auth_required(client):
    response = await client.get("/api/v1/filesystem")
    assert response.status_code in (401, 403)


async def test_empty_folder(auth_client, tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    response = await auth_client.get("/api/v1/filesystem", params={"path": str(folder)})
    assert response.status_code == 200
    assert response.json()["directories"] == []


async def test_inaccessible_folder(auth_client, tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("test denial")

    monkeypatch.setattr("app.api.routes_filesystem.os.scandir", denied)
    response = await auth_client.get("/api/v1/filesystem", params={"path": str(tmp_path)})
    assert response.status_code == 403
    assert "permission" in response.json()["detail"]
