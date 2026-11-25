"""Health endpoint — liveness/readiness with no secrets."""

from __future__ import annotations

from fastapi import APIRouter, Request

health_router = APIRouter(tags=["system"])


@health_router.get("/health")
async def health(request: Request) -> dict:
    """Liveness/readiness check. The only API route that needs no token (container healthcheck)."""
    settings = request.app.state.settings

    # Check DB connectivity
    db_ok = True
    try:
        from sqlalchemy import text

        from app.database.session import get_engine

        engine = get_engine(settings)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "version": "0.1.0",
    }
