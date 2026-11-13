"""Settings endpoint — global concurrency, polling, retries, retention."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.security import RequireAuth

settings_router = APIRouter(tags=["settings"])


class SettingsResponse(BaseModel):
    max_concurrent_download_jobs: int
    max_concurrent_verify_jobs: int
    max_concurrent_extract_jobs: int
    max_concurrent_publish_jobs: int
    max_concurrent_import_jobs: int
    completed_history_days: int
    discovery_interval_seconds: int
    retry_limit: int
    stage_lease_seconds: int


class SettingsPatch(BaseModel):
    max_concurrent_download_jobs: int | None = None
    max_concurrent_verify_jobs: int | None = None
    max_concurrent_extract_jobs: int | None = None
    max_concurrent_publish_jobs: int | None = None
    max_concurrent_import_jobs: int | None = None
    completed_history_days: int | None = None
    discovery_interval_seconds: int | None = None
    retry_limit: int | None = None
    stage_lease_seconds: int | None = None


@settings_router.get("/settings", response_model=SettingsResponse)
async def get_settings_api(request: Request) -> SettingsResponse:
    settings = request.app.state.settings
    return SettingsResponse(
        max_concurrent_download_jobs=settings.max_concurrent_download_jobs,
        max_concurrent_verify_jobs=settings.max_concurrent_verify_jobs,
        max_concurrent_extract_jobs=settings.max_concurrent_extract_jobs,
        max_concurrent_publish_jobs=settings.max_concurrent_publish_jobs,
        max_concurrent_import_jobs=settings.max_concurrent_import_jobs,
        completed_history_days=settings.completed_history_days,
        discovery_interval_seconds=settings.discovery_interval_seconds,
        retry_limit=settings.retry_limit,
        stage_lease_seconds=settings.stage_lease_seconds,
    )


@settings_router.patch("/settings", response_model=SettingsResponse)
async def patch_settings_api(
    body: SettingsPatch, request: Request, user: RequireAuth
) -> SettingsResponse:
    settings = request.app.state.settings
    updates = body.model_dump(exclude_none=True)

    # Apply to in-memory settings
    for field, value in updates.items():
        setattr(settings, field, value)

    # Persist to DB (app_settings table)
    from app.database.session import get_session_factory
    from app.database.repositories import SettingsRepository

    factory = get_session_factory(settings)
    async with factory() as session:
        repo = SettingsRepository(session)
        for field, value in updates.items():
            await repo.set(f"setting:{field}", value)
        await session.commit()

    # Apply concurrency limits to live scheduler
    if hasattr(request.app.state, "scheduler") and any(
        k in updates for k in [
            "max_concurrent_download_jobs", "max_concurrent_verify_jobs",
            "max_concurrent_extract_jobs", "max_concurrent_publish_jobs",
            "max_concurrent_import_jobs",
        ]
    ):
        request.app.state.scheduler.update_concurrency_limits()

    return await get_settings_api(request)
