"""FastAPI application entry point with lifespan, static mounting, and CLI."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def _alembic_config(settings: Settings):
    from pathlib import Path

    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "backend" / "migrations"))
    # The app owns logging; alembic.ini's config would replace its handlers (log view, file).
    cfg.attributes["configure_logger"] = False
    return cfg


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application startup and shutdown lifecycle."""
    settings: Settings = app.state.settings
    logging.basicConfig(level=getattr(logging, settings.log_level))

    # Capture recent log records in memory so they can be shown in the UI.
    from app.logging_buffer import install_log_handler, remove_log_handler

    install_log_handler()

    if settings.demo:
        # Throwaway database: a fresh OS temp folder per run, deleted on shutdown.
        import tempfile

        settings.config_dir = Path(tempfile.mkdtemp(prefix="haularr-demo-"))
        os.environ["HAULARR_CONFIG_DIR"] = str(settings.config_dir)  # migrations read it

    # Ensure config dir exists
    settings.config_dir.mkdir(parents=True, exist_ok=True)

    from app.logging_buffer import install_file_handler, remove_file_handler

    install_file_handler(
        settings.config_dir / "logs" / "haularr.log",
        max_bytes=settings.log_file_max_mb * 1024 * 1024,
        backups=settings.log_file_backups,
    )

    # Initialize database
    from app.database.session import close_engine, get_engine

    get_engine(settings)

    # Run migrations on startup
    logger.info("Running database migrations...")
    from alembic import command

    os.environ.setdefault("HAULARR_CONFIG_DIR", str(settings.config_dir))
    alembic_cfg = _alembic_config(settings)
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

    from app.jobs.recovery import Recovery
    from app.jobs.scheduler import JobScheduler

    if settings.demo:
        # Fake data only: nothing may run against the made-up hosts. The scheduler and
        # supervisor exist (routes use them) but never start.
        from app.demo import run_ticker, seed

        await seed(settings, app.state.master_key)
        from app.jobs.supervisor import DiscoverySupervisor

        app.state.scheduler = JobScheduler(settings)
        app.state.supervisor = DiscoverySupervisor(settings, app.state.master_key)
        demo_task = asyncio.create_task(run_ticker(settings))
        logger.warning("DEMO MODE: showing fake data; background services are off")
        yield
        demo_task.cancel()
        try:
            await demo_task
        except asyncio.CancelledError:
            pass
        await close_engine()
        remove_log_handler()
        remove_file_handler()
        import shutil

        shutil.rmtree(settings.config_dir, ignore_errors=True)
        return

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
        except (TimeoutError, asyncio.CancelledError):
            pass
    if hasattr(app.state, "supervisor"):
        await supervisor.stop()
    if hasattr(app.state, "scheduler"):
        await scheduler.stop()
    await close_engine()
    remove_log_handler()
    remove_file_handler()
    logger.info("Haularr stopped.")


async def _load_persisted_settings(settings: Settings) -> None:
    """Load settings previously saved to DB (overrides env/file defaults)."""
    _SETTING_FIELDS = [
        "max_concurrent_download_jobs",
        "max_concurrent_verify_jobs",
        "max_concurrent_extract_jobs",
        "max_concurrent_publish_jobs",
        "max_concurrent_import_jobs",
        "completed_history_days",
        "discovery_interval_seconds",
        "retry_limit",
        "stage_lease_seconds",
    ]
    try:
        from app.database.repositories import SettingsRepository
        from app.database.session import get_session_factory

        factory = get_session_factory(settings)
        async with factory() as session:
            repo = SettingsRepository(session)
            for field in _SETTING_FIELDS:
                value = await repo.get(f"setting:{field}")
                if value is not None:
                    setattr(settings, field, value)
    except Exception as exc:
        logger.debug("Could not load persisted settings (may be first run): %s", exc)


OPENAPI_TAGS = [
    {"name": "auth", "description": "Admin account setup and login (no token required)."},
    {
        "name": "sources",
        "description": "Torrent clients to watch, their FTP fetch config and tag rules.",
    },
    {
        "name": "source-items",
        "description": "Inventory of torrents seen on the sources; queue them as jobs.",
    },
    {
        "name": "jobs",
        "description": "Download/verify/extract/import pipeline runs and their controls.",
    },
    {"name": "libraries", "description": "Sonarr/Radarr instances that imports are handed to."},
    {
        "name": "system",
        "description": "Health, dashboard counts, settings, logs and config export.",
    },
    {"name": "events", "description": "Server-Sent Event streams of changes, for live UIs."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the FastAPI application."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Haularr",
        description=(
            "Download Orchestrator for self-hosted media automation.\n\n"
            "All endpoints except `/auth/setup`, `POST /auth/login` and `GET /health` "
            "require `Authorization: Bearer <token>`; get a token from `POST /auth/login`.\n\n"
            "Everything is available as plain request/response JSON. The `events` streams are "
            "an optional push channel for UIs: they carry changes only, so a client fetches "
            "current state from the regular endpoints after (re)connecting."
        ),
        version="0.1.0",
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Every API route requires a bearer token except login/setup (how a token is obtained)
    # and health (polled by the container healthcheck, exposes nothing).
    from fastapi import Depends

    from app.api import (
        routes_auth,
        routes_dashboard,
        routes_export,
        routes_filesystem,
        routes_health,
        routes_jobs,
        routes_libraries,
        routes_logs,
        routes_settings,
        routes_source_items,
        routes_sources,
        routes_sse,
    )
    from app.security import get_current_user

    api_prefix = "/api/v1"
    app.include_router(routes_health.health_router, prefix=api_prefix)
    app.include_router(routes_auth.auth_router, prefix=api_prefix)
    auth = [Depends(get_current_user)]
    for module in (
        routes_sources,
        routes_source_items,
        routes_jobs,
        routes_libraries,
        routes_dashboard,
        routes_settings,
        routes_export,
        routes_filesystem,
        routes_logs,
        routes_sse,
    ):
        app.include_router(module.router, prefix=api_prefix, dependencies=auth)

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
    """CLI entry point for `python -m app.main` or `haularr`. Pass `--reload` in development."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(
        prog="haularr",
        description="Run the Haularr server. Configure via HAULARR_* environment variables or .env.",
    )
    parser.add_argument(
        "--reload", action="store_true", help="restart on code changes (development)"
    )
    reload = parser.parse_args().reload
    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=1,  # Single process — scheduler is in-process
        log_level=settings.log_level.lower(),
        # Event streams never end on their own: without this, Ctrl+C waits on open browser tabs.
        timeout_graceful_shutdown=3,
        reload=reload,
        reload_dirs=[str(Path(__file__).parent)] if reload else None,
    )


# Module-level app for uvicorn --reload
app = create_app()


if __name__ == "__main__":
    cli()
