"""The source torrent identity must survive the job-to-Arr import handoff."""

import json

import pytest
import respx
from app.database.models import Job, LibraryInstance, MediaMatch, SourceItem
from app.database.session import get_session_factory
from app.domain.models import StageRunStatus
from app.jobs.runner import JobRunner

from tests.unit.test_waiting_fetch import _job


@pytest.mark.parametrize("adapter_type", ["sonarr", "radarr"])
@pytest.mark.parametrize("infohash", ["85921a23d6a55fe2264d5b3515625205e2e954f3", None])
@pytest.mark.parametrize("skip_library", [False, True])
@respx.mock
async def test_job_import_links_every_accepted_file_to_source_torrent(
    app, settings, adapter_type, infohash, skip_library
):
    _, job_id = await _job(settings, "running")
    async with get_session_factory(settings)() as session:
        job = await session.get_one(Job, job_id)
        item = await session.get_one(SourceItem, job.source_item_id)
        item.infohash = infohash
        # An arbitrary source ID must never be used as a torrent hash fallback.
        item.remote_id = "unrelated-source-id"
        library = LibraryInstance(
            name="Library",
            adapter_type=adapter_type,
            base_url="http://arr",
            api_key_secret_ref="key",
            options_json={"import_mode": "Move"},
        )
        session.add(library)
        await session.flush()
        session.add(
            MediaMatch(
                source_item_id=item.id,
                library_instance_id=library.id,
                media_type="series" if adapter_type == "sonarr" else "movie",
                catalog_id=42,
                episode_ids_json=[1, 2],
            )
        )
        job.stage = "import"
        job.config_snapshot_json = {
            **job.config_snapshot_json,
            "library_instance_id": library.id,
            "completed_directory": "/completed",
            "skip_library": skip_library,
        }
        await session.commit()

    candidates = [
        {
            "path": f"/completed/T/episode{n}.mkv",
            "series": {"id": 42},
            "movie": {"id": 42},
            "episodes": [{"id": n}],
            "quality": {"quality": {"name": "Bluray-1080p"}},
            "rejections": [{"reason": "Sample"}] if n == 3 else [],
        }
        for n in (1, 2, 3)
    ]
    inspect = respx.get("http://arr/api/v3/manualimport").respond(200, json=candidates)
    submit = respx.post("http://arr/api/v3/command").respond(201, json={"id": 123})
    respx.get("http://arr/api/v3/command/123").respond(200, json={"status": "completed"})
    respx.get("http://arr/api/v3/episode").respond(
        200, json=[{"id": n, "hasFile": True} for n in (1, 2)]
    )
    respx.get("http://arr/api/v3/movie/42").respond(200, json={"hasFile": True})

    result = await JobRunner(settings, job_id, "import", "tok").execute()

    assert result.status == StageRunStatus.SUCCEEDED, result
    # Keep inspection on the published folder: downloadId would override it in Sonarr.
    assert set(inspect.calls[0].request.url.params) == {"folder"}
    payload = json.loads(submit.calls[0].request.content)
    assert payload["importMode"] == "Move"
    assert len(payload["files"]) == 2
    assert all("episode3" not in f["path"] for f in payload["files"])
    for imported_file in payload["files"]:
        if infohash:
            assert imported_file.get("downloadId") == infohash.upper()
        else:
            assert "downloadId" not in imported_file
