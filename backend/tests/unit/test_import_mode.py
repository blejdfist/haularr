"""Library import choices must reach the Arr command, including legacy defaults."""

import json
import shutil

import httpx
import pytest
from app.adapters.libraries import create_library_adapter
from app.domain.models import ImportCandidate
from app.processing.cleanup import cleanup_path_a, cleanup_path_b
from app.processing.publication import publish_item


@pytest.mark.parametrize("adapter_type", ["sonarr", "radarr"])
@pytest.mark.parametrize(
    ("options", "expected"),
    [
        (None, "Copy"),
        ({}, "Copy"),
        ({"import_mode": "Copy"}, "Copy"),
        ({"import_mode": "Move"}, "Move"),
    ],
)
async def test_import_mode_reaches_arr_command(monkeypatch, adapter_type, options, expected):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(201, json={"id": 123})

    adapter = create_library_adapter("lib", adapter_type, "http://arr", "key", options)
    monkeypatch.setattr(
        adapter,
        "_make_client",
        lambda: httpx.AsyncClient(base_url="http://arr", transport=httpx.MockTransport(respond)),
    )
    candidate = ImportCandidate(
        relative_path="episode.mkv",
        absolute_path="/completed/episode.mkv",
        media_id=42,
        episode_ids=[7],
    )
    await adapter.submit_import([candidate])

    payload = json.loads(requests[0].content)
    assert payload["importMode"] == expected
    assert payload["files"][0]["path"] == "/completed/episode.mkv"


async def test_library_import_mode_persists_and_rejects_invalid_values(auth_client):
    response = await auth_client.post(
        "/api/v1/libraries",
        json={
            "name": "TV",
            "adapter_type": "sonarr",
            "base_url": "http://arr",
            "api_key_secret_ref": "key",
            "options": {"import_mode": "Move"},
        },
    )
    assert response.status_code == 201
    library_id = response.json()["id"]
    response = await auth_client.patch(
        f"/api/v1/libraries/{library_id}",
        json={
            "options": {"import_mode": "Copy", "path_mappings": []},
        },
    )
    assert response.status_code == 200
    saved = await auth_client.get(f"/api/v1/libraries/{library_id}")
    assert saved.json()["options"]["import_mode"] == "Copy"
    response = await auth_client.patch(
        f"/api/v1/libraries/{library_id}",
        json={
            "options": {"import_mode": "invalid"},
        },
    )
    assert response.status_code == 422


async def test_library_create_rejects_invalid_import_mode(auth_client):
    response = await auth_client.post(
        "/api/v1/libraries",
        json={
            "name": "TV",
            "adapter_type": "sonarr",
            "base_url": "http://arr",
            "api_key_secret_ref": "key",
            "options": {"import_mode": "invalid"},
        },
    )
    assert response.status_code == 422


def test_copy_cleanup_removes_archives_and_extracted_sources_but_keeps_library(tmp_path):
    staging = tmp_path / "staging"
    completed = tmp_path / "completed"
    release = staging / "release"
    release.mkdir(parents=True)
    (release / "release.rar").write_bytes(b"archive volume")
    (release / "release.r00").write_bytes(b"second volume")
    (release / "episode.mkv").write_bytes(b"extracted media")

    published = publish_item(
        release, str(completed), {"release/release.rar", "release/release.r00"}
    )
    assert published.success
    assert (release / "release.rar").exists()
    source = completed / "release" / "episode.mkv"
    library_file = tmp_path / "library" / "episode.mkv"
    library_file.parent.mkdir()
    shutil.copy2(source, library_file)

    # A copy remains untouched until the library import has been confirmed.
    pending = cleanup_path_b(str(completed), "release", "job", True, False)
    assert pending.skipped_b
    assert source.exists()

    archives = cleanup_path_a(str(staging), "release", "job")
    media = cleanup_path_b(str(completed), "release", "job", True, True)
    assert archives.success and media.success
    assert set(archives.deleted) == {"release.rar", "release.r00"}
    assert media.deleted == ["episode.mkv"]
    assert not release.exists()
    assert not source.parent.exists()
    assert library_file.read_bytes() == b"extracted media"
