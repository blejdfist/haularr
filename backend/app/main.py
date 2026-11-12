"""FastAPI application entry point with lifespan, static mounting, and CLI."""

from __future__ import annotations

import logging
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
    import os

    os.environ.setdefault("HAULARR_CONFIG_DIR", str(settings.config_dir))
    alembic_cfg = Config("alembic.ini")
    try:
        command.upgrade(alembic_cfg, "head")
        logger.info("Migrations complete.")
    except Exception as exc:
        logger.error("Migration failed: %s", exc)

    # Initialize master key
    from app.security import get_or_create_master_key
    app.state.master_key = get_or_create_master_key(settings.config_dir)
    logger.info("Master key initialized at %s/.master_key", settings.config_dir)

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

    logger.info("Haularr started on %s:%d", settings.host, settings.port)

    yield

    # Shutdown — stop scheduler first
    logger.info("Shutting down...")
    if hasattr(app.state, "scheduler"):
        await scheduler.stop()
    await close_engine()
    logger.info("Haularr stopped.")


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
