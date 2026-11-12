"""Health endpoint — liveness/readiness with no secrets."""

from __future__ import annotations

from fastapi import APIRouter, Request

health_router = APIRouter(tags=["health"])


@health_router.get("/health")
async def health(request: Request) -> dict:
    """Liveness/readiness check."""
    settings = request.app.state.settings

    # Check DB connectivity
    db_ok = True
    try:
        from app.database.session import get_engine
        from sqlalchemy import text

        engine = get_engine(settings)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "scheduler": "idle",  # Will be updated when scheduler is added
        "version": "0.1.0",
    }
