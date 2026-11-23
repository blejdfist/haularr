"""FastAPI application entry point with lifespan, static mounting, and CLI."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle."""
    settings: Settings = app.state.settings
    logging.basicConfig(level=getattr(logging, settings.log_level))

    # Ensure config dir exists
    settings.config_dir.mkdir(parents=True, exist_ok=True)

    # Initialize database
    from app.database.session import get_engine, close_engine
    engine = get_engine(settings)

    # Run migrations on startup
    logger.info("Running database migrations...")
    from alembic.config import Config
    from alembic import command
    import asyncio
    import os
    from pathlib import Path

    os.environ.setdefault("HAULARR_CONFIG_DIR", str(settings.config_dir))
    root = Path(__file__).resolve().parents[2]
    alembic_cfg = Config(str(root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(root / "backend" / "migrations"))
    # env.py calls asyncio.run(), which can't nest in this loop; run it in a thread.
    # Failure is fatal: serving on a stale schema corrupts data.
    await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
    logger.info("Migrations complete.")

    # Initialize master key
    from app.security import get_or_create_master_key
    app.state.master_key = get_or_create_master_key(settings.config_dir)
    logger.info("Master key initialized at %s/.master_key", settings.config_dir)

    # Load persisted settings from DB (overrides env/file defaults)
    await _load_persisted_settings(settings)

    # Initialize and start scheduler
    from app.jobs.scheduler import JobScheduler
    from app.jobs.recovery import Recovery

    # Recover expired leases first
    recovery = Recovery(settings)
    reclaimed = await recovery.recover_expired_leases()
    if reclaimed:
        logger.info("Recovered %d expired jobs on startup", reclaimed)

    scheduler = JobScheduler(settings)
    app.state.scheduler = scheduler
    await scheduler.start()

    # Start discovery supervisor
    from app.jobs.supervisor import DiscoverySupervisor
    supervisor = DiscoverySupervisor(settings, app.state.master_key)
    app.state.supervisor = supervisor
    await supervisor.start()

    # Start retention background task
    from app.jobs.retention import RetentionJob
    retention = RetentionJob(settings)
    app.state.retention_task = asyncio.create_task(retention.run_periodic(3600))

    logger.info("Haularr started on %s:%d", settings.host, settings.port)

    yield

    # Shutdown — stop supervisor, scheduler, and retention first
    logger.info("Shutting down...")
    if hasattr(app.state, "retention_task"):
        app.state.retention_task.cancel()
        try:
            await asyncio.wait_for(app.state.retention_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    if hasattr(app.state, "supervisor"):
        await supervisor.stop()
    if hasattr(app.state, "scheduler"):
        await scheduler.stop()
    await close_engine()
    logger.info("Haularr stopped.")


async def _load_persisted_settings(settings: Settings) -> None:
    """Load settings previously saved to DB (overrides env/file defaults)."""
    _SETTING_FIELDS = [
        "max_concurrent_download_jobs", "max_concurrent_verify_jobs",
        "max_concurrent_extract_jobs", "max_concurrent_publish_jobs",
        "max_concurrent_import_jobs", "completed_history_days",
        "discovery_interval_seconds", "retry_limit", "stage_lease_seconds",
    ]
    try:
        from app.database.session import get_session_factory
        from app.database.repositories import SettingsRepository

        factory = get_session_factory(settings)
        async with factory() as session:
            repo = SettingsRepository(session)
            for field in _SETTING_FIELDS:
                value = await repo.get(f"setting:{field}")
                if value is not None:
                    setattr(settings, field, value)
    except Exception as exc:
        logger.debug("Could not load persisted settings (may be first run): %s", exc)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Haularr",
        description="Download Orchestrator for self-hosted media automation",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Register API routers
    from app.api.routes import (
        auth_router,
        dashboard_router,
        health_router,
        jobs_router,
        libraries_router,
        settings_router,
        source_items_router,
        sources_router,
        transfers_router,
    )
    from app.api.routes_sse import sse_router
    from app.api.routes_export import export_router

    api_prefix = "/api/v1"
    app.include_router(health_router, prefix=api_prefix)
    app.include_router(auth_router, prefix=api_prefix)
    app.include_router(settings_router, prefix=api_prefix)
    app.include_router(sources_router, prefix=api_prefix)
    app.include_router(source_items_router, prefix=api_prefix)
    app.include_router(transfers_router, prefix=api_prefix)
    app.include_router(libraries_router, prefix=api_prefix)
    app.include_router(jobs_router, prefix=api_prefix)
    app.include_router(dashboard_router, prefix=api_prefix)
    app.include_router(sse_router, prefix=api_prefix)
    app.include_router(export_router, prefix=api_prefix)

    # Serve static frontend (SPA fallback)
    static_dir = settings.static_dir
    if static_dir.exists() and (static_dir / "index.html").exists():
        # Mount assets if the directory exists
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa_fallback(request: Request, path: str):
            # API routes take precedence (already matched by this point)
            file_path = static_dir / path
            if file_path.is_file():
                return FileResponse(str(file_path))
            # SPA fallback to index.html
            index = static_dir / "index.html"
            if index.exists():
                return FileResponse(str(index))
            return JSONResponse(
                {"detail": "Frontend not built. Run pnpm build in frontend/."},
                status_code=404,
            )

    return app


def cli() -> None:
    """CLI entry point for `python -m app.main` or `haularr`."""
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=1,  # Single process — scheduler is in-process
        log_level=settings.log_level.lower(),
    )


# Module-level app for uvicorn --reload
app = create_app()


if __name__ == "__main__":
    cli()
