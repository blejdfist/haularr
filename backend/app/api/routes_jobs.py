"""Jobs: pipeline runs for queued source items, and their controls."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import LibraryInstance, SourceItem

from app.database.repositories import JobRepository
from app.database.session import get_session

router = APIRouter(tags=["jobs"])



@router.get("/jobs")
async def list_jobs(
    status: str | None = Query(None, description="Comma-separated statuses, e.g. `failed,paused`."),
    stage: str | None = Query(None, description="Current stage, e.g. `download`."),
    source_id: str | None = Query(None),
    sort: Literal["newest", "attention"] = Query(
        "newest", description="`attention` puts jobs needing action first."
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """List jobs with filters and paging. Items carry `title` and `library_name`."""
    repo = JobRepository(session)
    jobs, total = await repo.list_filtered(
        status=[x for x in status.split(",") if x] if status else None,
        stage=stage, source_id=source_id, offset=offset, limit=limit, sort=sort,
    )
    titles = dict((await session.execute(
        select(SourceItem.id, SourceItem.title).where(
            SourceItem.id.in_([j.source_item_id for j in jobs])
        )
    )).all())
    libs = dict((await session.execute(select(LibraryInstance.id, LibraryInstance.name))).all())
    return {
        "items": [
            {
                **_job_to_dict(j),
                "title": titles.get(j.source_item_id),
                "library_name": libs.get(j.config_snapshot_json.get("library_instance_id")),
            }
            for j in jobs
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)):
    """Get one job with its stage runs, files (with transfer status) and event timeline."""
    repo = JobRepository(session)
    obj = await repo.get(job_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Job not found")
    result = _job_to_dict(obj)
    library_id = (obj.config_snapshot_json or {}).get("library_instance_id")
    library = await session.get(LibraryInstance, library_id) if library_id else None
    result["library_name"] = library.name if library else None
    result["stage_runs"] = [
        {
            "id": r.id,
            "stage": r.stage,
            "attempt": r.attempt,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "ended_at": r.ended_at.isoformat() if r.ended_at else None,
            "error_code": r.error_code,
            "error_detail": r.error_detail,
            "progress": r.progress_json,
        }
        for r in obj.stage_runs
    ]
    result["files"] = [
        {
            "id": f.id,
            "remote_relpath": f.remote_relpath,
            "size_bytes": f.size_bytes,
            "bytes_received": f.bytes_received,
            "transfer_status": f.transfer_status,
            "verified_at": f.verified_at.isoformat() if f.verified_at else None,
        }
        for f in obj.job_files
    ]
    result["events"] = [
        {
            "id": e.id,
            "created_at": e.created_at.isoformat(),
            "severity": e.severity,
            "kind": e.kind,
            "stage": e.stage,
            "message": e.message,
            "details": e.details_json,
        }
        for e in obj.events
    ]
    return result


@router.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str, session: AsyncSession = Depends(get_session)):
    """Pause a job; the scheduler skips it until resumed."""
    repo = JobRepository(session)
    obj = await repo.update(job_id, status="paused")
    if not obj:
        raise HTTPException(status_code=404, detail="Job not found")
    await repo.add_event(
        job_id=job_id, severity="info", kind="job.paused", message="Job paused by user"
    )
    await session.commit()
    return {"status": "paused", "job_id": job_id}


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str, session: AsyncSession = Depends(get_session)):
    """Resume a paused job."""
    repo = JobRepository(session)
    obj = await repo.update(job_id, status="queued", next_run_at=None)
    if not obj:
        raise HTTPException(status_code=404, detail="Job not found")
    await repo.add_event(
        job_id=job_id, severity="info", kind="job.resumed", message="Job resumed by user"
    )
    await session.commit()
    return {"status": "queued", "job_id": job_id}


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, session: AsyncSession = Depends(get_session)):
    """Retry a failed job from its current stage, resetting its attempt count."""
    repo = JobRepository(session)
    obj = await repo.update(
        job_id, status="queued", attempts=0, next_run_at=None, error_code=None, error_detail=None
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Job not found")
    await repo.add_event(
        job_id=job_id, severity="info", kind="job.retry", message="Job retry requested by user"
    )
    await session.commit()
    return {"status": "queued", "job_id": job_id}


@router.post("/jobs/{job_id}/restart")
async def restart_job(job_id: str, session: AsyncSession = Depends(get_session)):
    """Run the job again from the first stage, e.g. after its files were deleted."""
    from sqlalchemy import delete

    from app.database.models import JobFile
    from app.domain.models import JobStage

    repo = JobRepository(session)
    obj = await repo.update(
        job_id, stage=JobStage.CHECK_LIBRARY.value, status="queued", attempts=0,
        next_run_at=None, error_code=None, error_detail=None, ended_at=None,
        worker_token=None, lease_expires_at=None, download_bytes_done=0,
    )
    if not obj:
        raise HTTPException(status_code=404, detail="Job not found")
    await session.execute(delete(JobFile).where(JobFile.job_id == job_id))  # re-download from scratch
    await repo.add_event(
        job_id=job_id, severity="info", kind="job.restart", message="Job restarted from the beginning by user"
    )
    await session.commit()
    return {"status": "queued", "job_id": job_id}


@router.post("/jobs/{job_id}/approve")
async def approve_job(job_id: str, session: AsyncSession = Depends(get_session)):
    """Start a job whose tag rule doesn't process automatically; 409 unless it is waiting for that."""
    repo = JobRepository(session)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "waiting_approval":
        raise HTTPException(status_code=409, detail=f"Job is {job.status}, not waiting for approval")
    await repo.update(
        job_id, status="queued", error_code=None, error_detail=None,
        config_snapshot_json={**job.config_snapshot_json, "approved": True},
    )
    await repo.add_event(job_id=job_id, severity="info", kind="job.approved", message="Job started by user")
    await session.commit()
    return {"status": "queued", "job_id": job_id}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, session: AsyncSession = Depends(get_session)):
    """Cancel a job."""
    from datetime import datetime, timezone
    repo = JobRepository(session)
    obj = await repo.update(job_id, status="cancelled", ended_at=datetime.now(timezone.utc))
    if not obj:
        raise HTTPException(status_code=404, detail="Job not found")
    await repo.add_event(
        job_id=job_id, severity="info", kind="job.cancelled", message="Job cancelled by user"
    )
    await session.commit()
    return {"status": "cancelled", "job_id": job_id}


@router.post("/jobs/{job_id}/retry-import")
async def retry_import(job_id: str, session: AsyncSession = Depends(get_session)):
    """Run the library import again (from the inspect/import stage)."""
    repo = JobRepository(session)
    obj = await repo.update(job_id, stage="inspect_import", status="queued")
    if not obj:
        raise HTTPException(status_code=404, detail="Job not found")
    await repo.add_event(
        job_id=job_id, severity="info", kind="job.retry_import",
        message="Import retry requested by user"
    )
    await session.commit()
    return {"status": "queued", "job_id": job_id, "stage": "inspect_import"}


def _job_to_dict(obj: Any) -> dict:
    return {
        "id": obj.id,
        "source_item_id": obj.source_item_id,
        "rule_id": obj.rule_id,
        "status": obj.status,
        "stage": obj.stage,
        "attempts": obj.attempts,
        "priority": obj.priority,
        "config_snapshot": obj.config_snapshot_json,
        "next_run_at": obj.next_run_at.isoformat() if obj.next_run_at else None,
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
        "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
        "ended_at": obj.ended_at.isoformat() if obj.ended_at else None,
        "error_code": obj.error_code,
        "error_detail": obj.error_detail,
        "download_bytes_total": obj.download_bytes_total,
        "download_bytes_done": obj.download_bytes_done,
    }
