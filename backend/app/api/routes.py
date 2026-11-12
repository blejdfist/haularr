"""API route routers — all routers are defined here for easy registration."""

from __future__ import annotations

from app.api.routes_auth import auth_router
from app.api.routes_dashboard import dashboard_router
from app.api.routes_health import health_router
from app.api.routes_jobs import jobs_router
from app.api.routes_libraries import libraries_router
from app.api.routes_settings import settings_router
from app.api.routes_source_items import source_items_router
from app.api.routes_sources import sources_router
from app.api.routes_transfers import transfers_router

__all__ = [
    "auth_router",
    "dashboard_router",
    "health_router",
    "jobs_router",
    "libraries_router",
    "settings_router",
    "source_items_router",
    "sources_router",
    "transfers_router",
]
