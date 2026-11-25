"""Demo mode: seeds every job state, moves downloads along, and plays the showcase job."""

from __future__ import annotations

from app import demo
from app.demo import JOBS, LOOP_ID, STAGES, seed, showcase_once, tick


async def test_demo_seeds_and_ticks(app, auth_client):
    settings = app.state.settings
    await seed(settings, app.state.master_key)

    jobs = (await auth_client.get("/api/v1/jobs?limit=100")).json()
    assert jobs["total"] == len(JOBS) + 1  # + the showcase job
    states = {j["status"] for j in jobs["items"]}
    assert {"waiting_source", "running", "failed", "completed", "paused"} <= states

    transfer = next(
        j for j in jobs["items"] if j["stage"] == "transfer" and j["status"] == "running"
    )
    await tick(settings)
    after = (await auth_client.get(f"/api/v1/jobs/{transfer['id']}")).json()
    assert after["download_bytes_done"] > transfer["download_bytes_done"]


async def test_showcase_plays_every_stage_and_replays(app, auth_client, monkeypatch):
    monkeypatch.setattr(demo, "PACE", 0)
    settings = app.state.settings
    await seed(settings, app.state.master_key)

    play = demo._play
    seen: list[tuple[str, str, str]] = []

    async def spy(factory, stage, *a, **kw):  # the job must show each stage while it runs
        async def step(s, run, f):
            job = await s.get(demo.Job, LOOP_ID)
            seen.append((stage, job.stage, job.status))
            if inner:
                await inner(s, run, f)

        inner = kw.pop("step", None)
        await play(factory, stage, *a, step=step, **kw)

    monkeypatch.setattr(demo, "_play", spy)

    for _ in range(2):  # second pass starts over from a clean job
        await showcase_once(settings)
        job = (await auth_client.get(f"/api/v1/jobs/{LOOP_ID}")).json()
        assert job["status"] == "completed"
        assert sorted(r["stage"] for r in job["stage_runs"]) == sorted(STAGES)
        assert {r["status"] for r in job["stage_runs"]} == {"succeeded"}
        assert job["download_bytes_done"] == job["download_bytes_total"] > 0
        assert {f["transfer_status"] for f in job["files"]} == {"verified"}
        assert {s for s, _, _ in seen} == set(STAGES)
        for stage, job_stage, status in seen:
            assert job_stage == stage
            assert status == ("waiting_source" if stage == "source_download" else "running")
        seen.clear()
