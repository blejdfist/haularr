"""Config export endpoint — exports configuration with secrets redacted."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session

router = APIRouter(tags=["system"])



@router.get("/config/export")
async def export_config(request: Request, session: AsyncSession = Depends(get_session)):
    """Export settings, sources, tag rules, transfers and libraries with all secrets redacted."""
    from app.database.models import (
        LibraryInstance,
        SourceInstance,
        SourceLabelRule,
        TransferInstance,
        TransferEndpoint,
    )
    from sqlalchemy.orm import selectinload

    # Eagerly load all data inside the session
    sources_result = await session.execute(
        select(SourceInstance).options(selectinload(SourceInstance.label_rules))
    )
    sources = sources_result.scalars().all()

    labels_result = await session.execute(select(SourceLabelRule))
    labels = labels_result.scalars().all()

    transfers_result = await session.execute(
        select(TransferInstance).options(selectinload(TransferInstance.endpoints))
    )
    transfers = transfers_result.scalars().all()

    endpoints_result = await session.execute(select(TransferEndpoint))
    endpoints = endpoints_result.scalars().all()

    libraries_result = await session.execute(select(LibraryInstance))
    libraries = libraries_result.scalars().all()

    settings = request.app.state.settings

    # Build response while session is still active (avoid lazy-loading later)
    return {
        "settings": {
            "max_concurrent_download_jobs": settings.max_concurrent_download_jobs,
            "max_concurrent_verify_jobs": settings.max_concurrent_verify_jobs,
            "max_concurrent_extract_jobs": settings.max_concurrent_extract_jobs,
            "max_concurrent_publish_jobs": settings.max_concurrent_publish_jobs,
            "max_concurrent_import_jobs": settings.max_concurrent_import_jobs,
            "completed_history_days": settings.completed_history_days,
            "discovery_interval_seconds": settings.discovery_interval_seconds,
            "retry_limit": settings.retry_limit,
            "stage_lease_seconds": settings.stage_lease_seconds,
        },
        "sources": [
            {
                "id": s.id,
                "name": s.name,
                "adapter_type": s.adapter_type,
                "enabled": s.enabled,
                "poll_interval": s.poll_interval,
                "onboarding_state": s.onboarding_state,
                "connection_config": s.connection_config_json,  # Non-secret fields only
                "credential_ref": "***REDACTED***",             # Never export credential
                "default_transfer_id": s.default_transfer_id,
            }
            for s in sources
        ],
        "label_rules": [
            {
                "id": l.id,
                "source_id": l.source_id,
                "label": l.label,
                "priority": l.priority,
                "enabled": l.enabled,
                "automatic_processing": l.automatic_processing,
                "temporary_directory": l.temporary_directory,
                "completed_directory": l.completed_directory,
                "library_instance_id": l.library_instance_id,
                "transfer_override_id": l.transfer_override_id,
                "retention_days": l.retention_days,
            }
            for l in labels
        ],
        "transfers": [
            {
                "id": t.id,
                "name": t.name,
                "adapter_type": t.adapter_type,
                "enabled": t.enabled,
                "config": "***REDACTED***",
            }
            for t in transfers
        ],
        "transfer_endpoints": [
            {
                "id": e.id,
                "transfer_id": e.transfer_id,
                "name": e.name,
                "priority": e.priority,
                "host": e.host,
                "port": e.port,
                "credential_ref": "***REDACTED***",
            }
            for e in endpoints
        ],
        "libraries": [
            {
                "id": l.id,
                "name": l.name,
                "adapter_type": l.adapter_type,
                "base_url": l.base_url,
                "enabled": l.enabled,
                "api_key_secret_ref": "***REDACTED***",
            }
            for l in libraries
        ],
    }
