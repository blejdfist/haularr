"""Demo mode (``HAULARR_DEMO=true``): fake sources, libraries and jobs in every state.

On startup an empty database is filled with made-up data and the real background
services (scheduler, discovery, retention) are not started, so nothing reaches out to
the fake hosts. A ticker moves the downloading jobs along so the UI has live progress;
when a download finishes it starts over. One more job (the showcase) plays the whole
pipeline from seedbox download to cleanup, rests 30 seconds, and plays it again.

Demo mode ignores ``HAULARR_CONFIG_DIR``: each run gets a fresh OS temp folder for its
database, deleted on shutdown (see ``app.main.lifespan``).
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Job, JobEvent, JobFile, LibraryInstance, SourceInstance, SourceItem,
    SourceLabelRule, StageRun, User,
)
from app.database.session import get_session_factory
from app.security import hash_password
from app.settings import Settings

logger = logging.getLogger(__name__)

GB = 1024**3
MB = 1024**2
STAGES = [
    "source_download", "check_library", "transfer", "verify",
    "extract", "move", "inspect_import", "import", "cleanup",
]
TERMINAL = {"completed", "completed_with_warnings", "cancelled", "skipped", "failed"}

# The showcase job: walks every stage on a loop so visitors see the full flow.
LOOP_ID = "00000000-0000-4000-8000-000000000001"
LOOP_TITLE = "Paperclip.Odyssey.S01E01.1080p.WEB.h264"
LOOP_SIZE = int(4.2 * GB)
LOOP_REST = 30.0  # seconds between the job finishing and starting over
PACE = 1.0  # scales every showcase delay (tests set 0)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# (title, label, source, size, stage, status, extra). Titles are invented.
JOBS: list[tuple[str, str, str, int, str, str, dict[str, Any]]] = [
    ("Watching.Paint.Dry.S02E05.1080p.WEB.h264", "tv", "alpha", int(2.1 * GB),
     "source_download", "waiting_source", {"done": 0.35, "bps": 6 * MB}),
    ("Beige.The.Movie.2024.2160p.WEB-DL.DDP5.1.HDR.H265", "movies", "alpha", 18 * GB,
     "source_download", "waiting_source", {"done": 0.08, "bps": 22 * MB}),
    ("Spreadsheet.Stories.S01.1080p.BluRay.x264", "tv", "alpha", int(9.6 * GB),
     "transfer", "running", {"done": 0.42, "bps": 14 * MB, "files": 8}),
    ("The.Waiting.Room.2023.1080p.BluRay.x264", "movies", "alpha", int(8.4 * GB),
     "extract", "running", {"done": 0.6, "bps": 90 * MB}),
    ("Grass.Growing.Live.S03E01.720p.HDTV.x264", "tv", "alpha", 900 * MB,
     "check_library", "queued", {}),
    ("Tax.Form.Detectives.S04E02.1080p.WEB.h264", "manual", "alpha", int(1.8 * GB),
     "check_library", "waiting_approval", {}),
    ("Meetings.That.Could.Have.Been.Emails.S01E08.1080p.WEB.h264", "tv", "alpha", int(1.6 * GB),
     "check_library", "waiting_library", {"reason": "Series not found in Sonarr Demo"}),
    ("The.Stapler.2022.1080p.WEB-DL.DDP5.1.H264", "movies", "alpha", int(5.2 * GB),
     "transfer", "retry_wait",
     {"done": 0.71, "error": ("ftp_timeout", "Timed out reading from ftp.seedbox-alpha.invalid")}),
    ("Great.Beige.Walls.S02.720p.WEB.h264", "tv", "alpha", int(6.3 * GB),
     "transfer", "paused", {"done": 0.18, "files": 6}),
    ("Queue.Masters.S05E10.1080p.WEB.h264", "tv", "alpha", int(2.4 * GB),
     "import", "needs_attention",
     {"error": ("import_rejected", "Sonarr rejected the file: Not an upgrade for existing episode file")}),
    ("Elevator.Music.2021.1080p.BluRay.x264", "movies", "alpha", int(7.9 * GB),
     "verify", "failed",
     {"error": ("verify_failed", "elevator.music.2021.1080p.bluray.x264.rar: CRC mismatch (expected 3fa9c210, got 0be14d77)")}),
    ("Toast.Inspectors.S01E04.1080p.WEB.h264", "tv", "backup", int(1.5 * GB),
     "transfer", "waiting_transfer", {}),
    ("Small.Talk.S01E03.1080p.WEB.h264", "tv", "alpha", int(1.9 * GB),
     "cleanup", "completed", {"ago": 3}),
    ("Dial.Tone.2020.1080p.BluRay.x264", "movies", "alpha", int(9.1 * GB),
     "cleanup", "completed_with_warnings", {"ago": 20}),
    ("Filing.Cabinets.of.the.World.S02E04.1080p.WEB.h264", "tv", "alpha", int(1.7 * GB),
     "check_library", "skipped", {"ago": 40, "reason": "Episode already in Sonarr Demo"}),
    ("Puddle.Watch.S01E01.720p.WEB.h264", "tv", "backup", 800 * MB,
     "transfer", "cancelled", {"ago": 75, "done": 0.3}),
]

# Torrents on the sources that never became jobs (untagged, ignored, etc.).
LOOSE_ITEMS = [
    ("Fridge.Hum.Recordings.Vol.3.FLAC", ["music"], "not_eligible"),
    ("Gravel.A.Documentary.2019.720p.WEB", [], "no_label"),
    ("Bus.Timetables.Explained.S01.Complete.480p.DVDRip", ["tv"], "ignored"),
]


def _files(title: str, size: int, n: int) -> list[tuple[str, int]]:
    """Fake release contents: a split RAR set, or one .mkv for small releases."""
    base = title.lower()
    if n <= 1:
        return [(f"{title}/{base}.mkv", size)]
    part = size // n
    names = [f"{title}/{base}.rar"] + [f"{title}/{base}.r{i:02d}" for i in range(n - 1)]
    # Sorted like the ticker fills them (by path).
    return sorted((name, part if i < n - 1 else size - part * (n - 1)) for i, name in enumerate(names))


async def seed(settings: Settings, master_key: bytes) -> None:
    """Fill the (fresh, throwaway) demo database."""
    async with get_session_factory(settings)() as session:
        await _seed(session, master_key)
        await session.commit()
    logger.info("Demo data seeded in %s (log in as demo / demo)", settings.config_dir)


async def _seed(session: AsyncSession, master_key: bytes) -> None:
    from app.api.routes_sources import FetchConfig, PathMapping
    from app.services.source_fetch import upsert_source_fetch

    now = _now()
    session.add(User(username="demo", password_hash=hash_password("demo"), is_admin=True))

    sonarr = LibraryInstance(name="Sonarr Demo", adapter_type="sonarr",
                             base_url="http://sonarr.demo.invalid:8989", api_key_secret_ref="demo")
    radarr = LibraryInstance(name="Radarr Demo", adapter_type="radarr",
                             base_url="http://radarr.demo.invalid:7878", api_key_secret_ref="demo")
    alpha = SourceInstance(
        name="Seedbox Alpha", adapter_type="rtorrent",
        connection_config_json={"url": "https://seedbox-alpha.invalid/RPC2", "username": "demo"},
        onboarding_state="completed", initial_scan_at=now - timedelta(days=12),
        last_scan_at=now - timedelta(seconds=20),
    )
    backup = SourceInstance(
        name="Backup Box", adapter_type="rtorrent",
        connection_config_json={"url": "https://backup-box.invalid/RPC2", "username": "demo"},
        onboarding_state="completed", initial_scan_at=now - timedelta(days=30),
        last_scan_at=now - timedelta(minutes=4),
        last_scan_error="Connection refused (backup-box.invalid:443)",
    )
    session.add_all([sonarr, radarr, alpha, backup])
    await session.flush()
    await upsert_source_fetch(session, alpha, FetchConfig(
        host="ftp.seedbox-alpha.invalid", username="demo", password="demo",
        path_mappings=[PathMapping(source_prefix="/home/demo/downloads", remote_prefix="/downloads")],
    ), master_key)

    def rule(src: SourceInstance, label: str, lib: LibraryInstance, auto: bool = True) -> SourceLabelRule:
        return SourceLabelRule(
            source_id=src.id, label=label, automatic_processing=auto, library_instance_id=lib.id,
            temporary_directory=f"/data/incoming/{label}", completed_directory=f"/data/completed/{label}",
        )

    rules = {
        ("alpha", "tv"): rule(alpha, "tv", sonarr),
        ("alpha", "movies"): rule(alpha, "movies", radarr),
        ("alpha", "manual"): rule(alpha, "manual", sonarr, auto=False),
        ("backup", "tv"): rule(backup, "tv", sonarr),
    }
    session.add_all(rules.values())
    await session.flush()
    sources = {"alpha": alpha, "backup": backup}

    for i, (title, label, src_key, size, stage, status, x) in enumerate(JOBS):
        src, r = sources[src_key], rules[(src_key, label)]
        created = now - timedelta(minutes=x.get("ago", 0) + 30 + i * 7)
        downloading = stage == "source_download"
        files = _files(title, size, x.get("files", 1 if size < 3 * GB else 5))
        item = SourceItem(
            source_id=src.id, remote_id=f"DEMO{i:036X}", title=title, labels_json=[label],
            source_status="active" if downloading else "completed",
            remote_path=f"/home/demo/downloads/{title}", size_bytes=size,
            completed_at=None if downloading else created, first_seen_at=created,
            last_seen_at=now, last_eligibility="eligible", eligible_rule_id=r.id,
            remote_metadata_json={"completed_bytes": int(size * x.get("done", 1)), "down_rate": x.get("bps", 0)},
        )
        session.add(item)
        await session.flush()

        ended = now - timedelta(minutes=x.get("ago", 0)) if status in TERMINAL else None
        err_code, err_detail = x.get("error", (None, None))
        in_transfer = stage == "transfer"
        transferred = int(size * x.get("done", 0)) if in_transfer else (size if STAGES.index(stage) > 2 else 0)
        job = Job(
            source_item_id=item.id, rule_id=r.id, priority=0, status=status, stage=stage,
            config_snapshot_json=_snapshot(src, r, title),
            attempts=2 if status == "retry_wait" else 1,
            next_run_at=now + timedelta(minutes=2) if status == "retry_wait" else None,
            created_at=created, ended_at=ended, error_code=err_code, error_detail=err_detail,
            download_bytes_total=size if STAGES.index(stage) >= 2 else 0,
            download_bytes_done=transferred,
        )
        session.add(job)
        await session.flush()

        if STAGES.index(stage) >= 2:
            left = transferred
            for path, fsize in files:
                got, left = min(fsize, left), left - min(fsize, left)
                state = "completed" if got == fsize else ("in_progress" if got and status == "running" else "pending")
                if STAGES.index(stage) > 3 and status != "failed":
                    state = "verified"
                session.add(JobFile(job_id=job.id, remote_relpath=path, size_bytes=fsize,
                                    bytes_received=got, transfer_status=state))

        session.add(JobEvent(job_id=job.id, created_at=created, kind="job.created",
                             message=f"Job created for tag '{label}'"))
        t = created
        for s in STAGES[: STAGES.index(stage) + 1]:
            current = s == stage
            if current:
                run_status = {
                    "running": "running", "waiting_source": "running", "retry_wait": "retry_wait",
                    "failed": "failed", "needs_attention": "needs_attention",
                    "completed": "succeeded", "completed_with_warnings": "succeeded",
                    "skipped": "skipped", "cancelled": "failed", "paused": "running",
                }.get(status)
                if run_status is None:  # queued / waiting_*: stage not started yet
                    break
            else:
                run_status = "succeeded"
            t += timedelta(minutes=2)
            open_run = run_status in ("running", "retry_wait")
            session.add(StageRun(
                job_id=job.id, stage=s, status=run_status, started_at=t,
                ended_at=None if open_run else t + timedelta(minutes=1),
                error_code=err_code if current else None, error_detail=err_detail if current else None,
                progress_json=_progress(s, title, size, files, x if current else {}, sonarr if label != "movies" else radarr),
            ))
            if not current:
                session.add(JobEvent(job_id=job.id, created_at=t, kind="stage.completed", stage=s,
                                     message=f"Stage {s} finished"))
        if err_code:
            session.add(JobEvent(job_id=job.id, created_at=now - timedelta(minutes=1),
                                 severity="error" if status == "failed" else "warning",
                                 kind="stage.error", stage=stage, message=err_detail))

    # The showcase job; run_showcase resets and plays it.
    r = rules[("alpha", "tv")]
    item = SourceItem(
        source_id=alpha.id, remote_id="DEMOLOOP", title=LOOP_TITLE, labels_json=["tv"],
        source_status="active", remote_path=f"/home/demo/downloads/{LOOP_TITLE}", size_bytes=LOOP_SIZE,
        first_seen_at=now, last_seen_at=now, last_eligibility="eligible", eligible_rule_id=r.id,
    )
    session.add(item)
    await session.flush()
    session.add(Job(id=LOOP_ID, source_item_id=item.id, rule_id=r.id, status="waiting_source",
                    stage="source_download", config_snapshot_json=_snapshot(alpha, r, LOOP_TITLE)))

    for j, (title, labels, verdict) in enumerate(LOOSE_ITEMS):
        session.add(SourceItem(
            source_id=alpha.id, remote_id=f"DEMOLOOSE{j:031X}", title=title, labels_json=labels,
            source_status="completed", remote_path=f"/home/demo/downloads/{title}",
            size_bytes=(j + 2) * GB, completed_at=now - timedelta(days=j + 1),
            last_eligibility=verdict, ignored_at=now if verdict == "ignored" else None,
        ))


def _snapshot(src: SourceInstance, r: SourceLabelRule, title: str) -> dict[str, Any]:
    return {
        "source_id": src.id, "source_name": src.name, "label": r.label,
        "transfer_id": src.default_transfer_id, "library_instance_id": r.library_instance_id,
        "temporary_directory": r.temporary_directory, "completed_directory": r.completed_directory,
        "title": title, "approved": r.automatic_processing,
    }


def _progress(stage: str, title: str, size: int, files: list[tuple[str, int]],
              x: dict[str, Any], library: LibraryInstance) -> dict[str, Any]:
    """What a stage run's progress looks like for this stage (see the runner)."""
    done = x.get("done", 1.0)
    if stage == "source_download":
        return {
            "bytes_done": int(size * done), "bytes_total": size, "bps": x.get("bps", 0), "message": "",
            "files": [{"path": p, "size_bytes": s, "done_bytes": int(s * done)} for p, s in files],
        }
    if stage == "check_library":
        return {"eligibility": "eligible", "library": f"{library.name} ({library.adapter_type})",
                "reason": x.get("reason", "Wanted by the library"), "evidence": {}}
    if stage == "verify":
        bad = x.get("error")
        return {"files": [{"path": p, "result": "failed" if bad and i == len(files) - 1 else "crc32 ok",
                           "detail": bad[1] if bad and i == len(files) - 1 else ""}
                          for i, (p, _) in enumerate(files)]}
    if stage == "extract":
        return {"bytes_done": int(size * done), "bytes_total": size,
                "archives": [{"archive": files[0][0], "files": None}]}
    return {}


async def tick(settings: Settings) -> None:
    """Advance seedbox downloads, FTP transfers and extractions by one second's worth."""
    async with get_session_factory(settings)() as session:
        rows = (await session.execute(
            select(Job, StageRun).join(StageRun, StageRun.job_id == Job.id).where(
                Job.status.in_(("running", "waiting_source")), Job.id != LOOP_ID,
                StageRun.stage == Job.stage, StageRun.status == "running",
            )
        )).all()
        for job, run in rows:
            p = dict(run.progress_json or {})
            if job.stage == "source_download":
                total = p.get("bytes_total") or 1
                done = p.get("bytes_done", 0) + p.get("bps", 0)
                done = 0 if done >= total else done  # loop forever
                p["bytes_done"] = done
                p["files"] = [{**f, "done_bytes": int(f["size_bytes"] * done / total)} for f in p.get("files", [])]
                run.progress_json = p
            elif job.stage == "extract":
                done = p.get("bytes_done", 0) + 90 * MB
                p["bytes_done"] = 0 if done >= p.get("bytes_total", 1) else done
                run.progress_json = p
            elif job.stage == "transfer":
                done = job.download_bytes_done + 14 * MB
                job.download_bytes_done = done = 0 if done >= job.download_bytes_total else done
                await _fill_files(session, job.id, done)
        await session.commit()


async def _fill_files(session: AsyncSession, job_id: str, done: int) -> None:
    """Spread ``done`` transferred bytes over the job's files in path order."""
    files = (await session.execute(
        select(JobFile).where(JobFile.job_id == job_id).order_by(JobFile.remote_relpath)
    )).scalars().all()
    for f in files:
        f.bytes_received = got = max(0, min(f.size_bytes, done))
        f.transfer_status = "completed" if got == f.size_bytes else ("in_progress" if got else "pending")
        done -= f.size_bytes


async def run_ticker(settings: Settings) -> None:
    async def ticks() -> None:
        while True:
            try:
                await tick(settings)
            except Exception:
                logger.exception("Demo tick failed")
            await asyncio.sleep(1.0)

    await asyncio.gather(ticks(), run_showcase(settings))


async def run_showcase(settings: Settings) -> None:
    while True:
        try:
            await showcase_once(settings)
        except Exception:
            logger.exception("Demo showcase failed")
        await asyncio.sleep(LOOP_REST * PACE)


async def showcase_once(settings: Settings) -> None:
    """Reset the showcase job and play it through every stage to completed."""
    factory = get_session_factory(settings)
    title, size = LOOP_TITLE, LOOP_SIZE
    files = _files(title, size, 5)
    mkv = f"{title.lower()}.mkv"
    published = f"/data/completed/tv/{title}"
    lib = LibraryInstance(name="Sonarr Demo", adapter_type="sonarr")

    async with factory() as s:
        for model in (StageRun, JobFile, JobEvent):
            await s.execute(delete(model).where(model.job_id == LOOP_ID))
        job = await s.get(Job, LOOP_ID)
        item = await s.get(SourceItem, job.source_item_id)
        item.source_status, item.completed_at = "active", None
        job.status, job.stage, job.created_at, job.ended_at = "waiting_source", "source_download", _now(), None
        job.download_bytes_done = job.download_bytes_total = 0
        s.add(JobEvent(job_id=LOOP_ID, kind="job.created", message="Job created for tag 'tv'"))
        await s.commit()

    secs = random.uniform(5, 10)

    async def download(s: AsyncSession, run: StageRun, f: float) -> None:
        run.progress_json = _progress("source_download", title, size, files,
                                      {"done": f, "bps": int(size / secs)}, lib)

    await _play(factory, "source_download", secs,
                _progress("source_download", title, size, files, {"done": 0, "bps": 0}, lib), step=download)
    async with factory() as s:
        job = await s.get(Job, LOOP_ID)
        item = await s.get(SourceItem, job.source_item_id)
        item.source_status, item.completed_at = "completed", _now()
        await s.commit()

    await _play(factory, "check_library", 2, {}, finish=_progress("check_library", title, size, files, {}, lib))

    async with factory() as s:
        (await s.get(Job, LOOP_ID)).download_bytes_total = size
        s.add_all(JobFile(job_id=LOOP_ID, remote_relpath=p, size_bytes=n, transfer_status="pending")
                  for p, n in files)
        await s.commit()

    async def transfer(s: AsyncSession, run: StageRun, f: float) -> None:
        done = int(size * f)
        (await s.get(Job, LOOP_ID)).download_bytes_done = done
        await _fill_files(s, LOOP_ID, done)
        run.progress_json = {"file": files[min(int(f * len(files)), len(files) - 1)][0],
                             "bytes_done": done, "bytes_total": size}

    await _play(factory, "transfer", random.uniform(5, 10), {"bytes_done": 0, "bytes_total": size},
                step=transfer)

    await _play(factory, "verify", 2.5, {"files": [{"path": p, "result": "checking"} for p, _ in files]},
                finish={"checks": len(files),
                        "files": [{"path": p, "result": "crc32 ok", "detail": ""} for p, _ in files]})
    async with factory() as s:
        for f in (await s.execute(select(JobFile).where(JobFile.job_id == LOOP_ID))).scalars():
            f.transfer_status = "verified"
        await s.commit()

    archive = {"archive": files[0][0], "files": None}

    async def extract(s: AsyncSession, run: StageRun, f: float) -> None:
        run.progress_json = {"bytes_done": int(size * f), "bytes_total": size, "archives": [archive]}

    await _play(factory, "extract", random.uniform(5, 10),
                {"bytes_done": 0, "bytes_total": size, "archives": [archive]}, step=extract,
                finish={"bytes_done": size, "bytes_total": size, "archives": [{**archive, "files": [mkv]}]})
    await _play(factory, "move", 1.5, {}, finish={"published_path": published, "files": [mkv]})
    candidate = f"{published}/{mkv}"
    await _play(factory, "inspect_import", 1.5, {}, finish={"candidates": [{
        "path": candidate, "quality": "WEBDL-1080p", "rejection_reasons": [],
        "media_id": 1, "episode_ids": [1]}]})
    await _play(factory, "import", 2, {}, finish={
        "imported": [candidate], "rejected": [], "skipped": [], "pending": False})
    await _play(factory, "cleanup", 1.5, {}, finish={
        "cleaned_a": f"/data/incoming/tv/{title}", "deleted_a": {"count": len(files), "bytes": size},
        "cleaned_b": published, "deleted_b": {"files": [], "bytes": 0}, "skipped_b": False})

    async with factory() as s:
        job = await s.get(Job, LOOP_ID)
        job.status, job.ended_at = "completed", _now()
        s.add(JobEvent(job_id=LOOP_ID, kind="job.completed", message="Job completed"))
        await s.commit()


async def _play(factory: Any, stage: str, seconds: float, start: dict[str, Any],
                step: Any = None, finish: dict[str, Any] | None = None) -> None:
    """One showcase stage: queued a moment, then running for ``seconds`` (``step`` gets the
    fraction done about once a second), then succeeded with ``finish`` as its progress."""
    async with factory() as s:
        job = await s.get(Job, LOOP_ID)
        if stage != "source_download":  # the seedbox download has no queue
            job.stage, job.status = stage, "queued"
            await s.commit()
            await asyncio.sleep(1 * PACE)
            job.status = "running"
        run = StageRun(job_id=LOOP_ID, stage=stage, status="running", started_at=_now(), progress_json=start)
        s.add(run)
        await s.commit()
        run_id = run.id

    n = max(1, round(seconds))
    for i in range(1, n + 1):
        await asyncio.sleep(seconds / n * PACE)
        if step:
            async with factory() as s:
                await step(s, await s.get(StageRun, run_id), i / n)
                await s.commit()

    async with factory() as s:
        run = await s.get(StageRun, run_id)
        run.status, run.ended_at = "succeeded", _now()
        if finish is not None:
            run.progress_json = finish
        s.add(JobEvent(job_id=LOOP_ID, kind="stage.completed", stage=stage, message=f"Stage {stage} finished"))
        await s.commit()
