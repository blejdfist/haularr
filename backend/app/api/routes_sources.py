"""Source instances and label rules endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import LabelRuleRepository, SourceRepository
from app.database.session import get_session_factory
from app.security import RequireAuth
from app.settings import Settings, get_settings

sources_router = APIRouter(tags=["sources"])


async def get_session(request: Request):
    settings: Settings = request.app.state.settings
    factory = get_session_factory(settings)
    async with factory() as session:
        yield session


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SourceCreate(BaseModel):
    name: str
    adapter_type: str  # "rtorrent" | "deluge"
    connection_secret_ref: str  # JSON blob of connection config
    default_transfer_id: str | None = None
    poll_interval: int = 30
    enabled: bool = True


class SourceResponse(BaseModel):
    id: str
    name: str
    adapter_type: str
    enabled: bool
    default_transfer_id: str | None
    poll_interval: int
    onboarding_state: str
    initial_scan_at: str | None
    last_scan_at: str | None

    class Config:
        from_attributes = True


class SourceUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    default_transfer_id: str | None = None
    poll_interval: int | None = None
    connection_secret_ref: str | None = None


class LabelRuleCreate(BaseModel):
    label: str
    priority: int = 0
    enabled: bool = True
    automatic_processing: bool = False
    temporary_directory: str
    completed_directory: str
    library_instance_id: str | None = None
    transfer_override_id: str | None = None
    retention_days: int | None = None
    pipeline_options: dict[str, Any] | None = None


class LabelRuleResponse(BaseModel):
    id: str
    source_id: str
    label: str
    priority: int
    enabled: bool
    automatic_processing: bool
    temporary_directory: str
    completed_directory: str
    library_instance_id: str | None
    transfer_override_id: str | None
    retention_days: int | None

    class Config:
        from_attributes = True


class LabelRuleUpdate(BaseModel):
    priority: int | None = None
    enabled: bool | None = None
    automatic_processing: bool | None = None
    temporary_directory: str | None = None
    completed_directory: str | None = None
    library_instance_id: str | None = None
    transfer_override_id: str | None = None
    retention_days: int | None = None


# ---------------------------------------------------------------------------
# Source instances
# ---------------------------------------------------------------------------


@sources_router.get("/sources")
async def list_sources(session: AsyncSession = Depends(get_session), user: RequireAuth = None):
    repo = SourceRepository(session)
    sources = await repo.list_all()
    return [_source_to_dict(s) for s in sources]


@sources_router.post("/sources", status_code=201)
async def create_source(
    body: SourceCreate,
    session: AsyncSession = Depends(get_session),
    user: RequireAuth = None,
):
    repo = SourceRepository(session)
    obj = await repo.create(
        name=body.name,
        adapter_type=body.adapter_type,
        connection_secret_ref=body.connection_secret_ref,
        default_transfer_id=body.default_transfer_id,
        poll_interval=body.poll_interval,
        enabled=body.enabled,
    )
    await session.commit()
    return _source_to_dict(obj)


@sources_router.get("/sources/{source_id}")
async def get_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    user: RequireAuth = None,
):
    repo = SourceRepository(session)
    obj = await repo.get(source_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Source not found")
    result = _source_to_dict(obj)
    result["label_rules"] = [_label_to_dict(r) for r in obj.label_rules]
    return result


@sources_router.patch("/sources/{source_id}")
async def update_source(
    source_id: str,
    body: SourceUpdate,
    session: AsyncSession = Depends(get_session),
    user: RequireAuth = None,
):
    repo = SourceRepository(session)
    updates = body.model_dump(exclude_none=True)
    obj = await repo.update(source_id, **updates)
    if not obj:
        raise HTTPException(status_code=404, detail="Source not found")
    await session.commit()
    return _source_to_dict(obj)


@sources_router.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    user: RequireAuth = None,
):
    repo = SourceRepository(session)
    await repo.delete(source_id)
    await session.commit()


@sources_router.post("/sources/{source_id}/test")
async def test_source(
    source_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: RequireAuth = None,
):
    repo = SourceRepository(session)
    obj = await repo.get(source_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Source not found")
    # Decrypt connection config
    import json
    from app.security import decrypt_secret

    master_key = request.app.state.master_key
    try:
        config = json.loads(obj.connection_secret_ref)
        # Decrypt password fields if present
        for key in ("password",):
            if key in config and isinstance(config[key], str) and config[key].startswith("enc:"):
                config[key] = decrypt_secret(config[key][4:], master_key)
    except Exception:
        config = {}

    from app.adapters.sources import create_source_adapter
    adapter = create_source_adapter(obj.id, obj.adapter_type, config)
    result = await adapter.test_connection()
    return result


@sources_router.post("/sources/{source_id}/scan")
async def scan_source(
    source_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: RequireAuth = None,
):
    """Trigger discovery/reconciliation for a source."""
    repo = SourceRepository(session)
    obj = await repo.get(source_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Source not found")

    from datetime import datetime, timezone

    await repo.update(
        source_id,
        last_scan_at=datetime.now(timezone.utc),
        onboarding_state="scanning" if obj.onboarding_state == "pending" else obj.onboarding_state,
    )
    await session.commit()
    return {"status": "scan_triggered", "source_id": source_id}


@sources_router.post("/sources/{source_id}/complete-onboarding")
async def complete_onboarding(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    user: RequireAuth = None,
):
    """Activate automatic processing for new items after admin acknowledges baseline."""
    repo = SourceRepository(session)
    obj = await repo.update(source_id, onboarding_state="completed")
    if not obj:
        raise HTTPException(status_code=404, detail="Source not found")
    # Enable automatic_processing on all label rules
    label_repo = LabelRuleRepository(session)
    rules = await label_repo.list_by_source(source_id)
    for rule in rules:
        await label_repo.update(rule.id, automatic_processing=True)
    await session.commit()
    return _source_to_dict(obj)


# ---------------------------------------------------------------------------
# Label rules
# ---------------------------------------------------------------------------


@sources_router.get("/sources/{source_id}/labels")
async def list_labels(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    user: RequireAuth = None,
):
    repo = LabelRuleRepository(session)
    rules = await repo.list_by_source(source_id)
    return [_label_to_dict(r) for r in rules]


@sources_router.post("/sources/{source_id}/labels", status_code=201)
async def create_label(
    source_id: str,
    body: LabelRuleCreate,
    session: AsyncSession = Depends(get_session),
    user: RequireAuth = None,
):
    # Verify source exists
    source_repo = SourceRepository(session)
    source = await source_repo.get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    # Check for duplicate label
    existing = await LabelRuleRepository(session).get_by_source_label(source_id, body.label)
    if existing:
        raise HTTPException(status_code=409, detail="Label rule already exists")

    repo = LabelRuleRepository(session)
    obj = await repo.create(
        source_id=source_id,
        label=body.label,
        priority=body.priority,
        enabled=body.enabled,
        automatic_processing=body.automatic_processing,
        temporary_directory=body.temporary_directory,
        completed_directory=body.completed_directory,
        library_instance_id=body.library_instance_id,
        transfer_override_id=body.transfer_override_id,
        retention_days=body.retention_days,
        pipeline_options_json=body.pipeline_options or {},
    )
    await session.commit()
    return _label_to_dict(obj)


@sources_router.patch("/sources/{source_id}/labels/{rule_id}")
async def update_label(
    source_id: str,
    rule_id: str,
    body: LabelRuleUpdate,
    session: AsyncSession = Depends(get_session),
    user: RequireAuth = None,
):
    repo = LabelRuleRepository(session)
    updates = body.model_dump(exclude_none=True)
    obj = await repo.update(rule_id, **updates)
    if not obj:
        raise HTTPException(status_code=404, detail="Label rule not found")
    await session.commit()
    return _label_to_dict(obj)


@sources_router.delete("/sources/{source_id}/labels/{rule_id}", status_code=204)
async def delete_label(
    source_id: str,
    rule_id: str,
    session: AsyncSession = Depends(get_session),
    user: RequireAuth = None,
):
    repo = LabelRuleRepository(session)
    await repo.delete(rule_id)
    await session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _source_to_dict(obj: Any) -> dict:
    return {
        "id": obj.id,
        "name": obj.name,
        "adapter_type": obj.adapter_type,
        "enabled": obj.enabled,
        "default_transfer_id": obj.default_transfer_id,
        "poll_interval": obj.poll_interval,
        "onboarding_state": obj.onboarding_state,
        "initial_scan_at": obj.initial_scan_at.isoformat() if obj.initial_scan_at else None,
        "last_scan_at": obj.last_scan_at.isoformat() if obj.last_scan_at else None,
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
    }


def _label_to_dict(obj: Any) -> dict:
    return {
        "id": obj.id,
        "source_id": obj.source_id,
        "label": obj.label,
        "priority": obj.priority,
        "enabled": obj.enabled,
        "automatic_processing": obj.automatic_processing,
        "temporary_directory": obj.temporary_directory,
        "completed_directory": obj.completed_directory,
        "library_instance_id": obj.library_instance_id,
        "transfer_override_id": obj.transfer_override_id,
        "retention_days": obj.retention_days,
    }
