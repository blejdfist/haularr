"""Source instances and label rules endpoints."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import LabelRuleRepository, SourceRepository
from app.database.session import get_session_factory
from app.security import OptionalAuth
from app.settings import Settings

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
    adapter_type: str  # "rtorrent"

    # Non-secret: host/url, port, username, TLS settings
    connection_config: dict[str, Any] = {}

    # Secret: plaintext password/token — will be encrypted before storage
    credential: str = ""

    default_transfer_id: str | None = None
    poll_interval: int = 30
    enabled: bool = True


class SourceUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    default_transfer_id: str | None = None
    poll_interval: int | None = None
    connection_config: dict[str, Any] | None = None
    credential: str | None = None  # plaintext; encrypted on save


class SourceTestRequest(BaseModel):
    """Test connection config before saving (no DB record required)."""
    adapter_type: str
    connection_config: dict[str, Any] = {}
    credential: str = ""


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
async def list_sources(session: AsyncSession = Depends(get_session), user: OptionalAuth = None):
    repo = SourceRepository(session)
    sources = await repo.list_all()
    return [_source_to_dict(s) for s in sources]


@sources_router.post("/sources", status_code=201)
async def create_source(
    body: SourceCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: OptionalAuth = None,
):
    master_key = request.app.state.master_key
    encrypted_cred = _encrypt_credential(body.credential, master_key) if body.credential else ""

    repo = SourceRepository(session)
    obj = await repo.create(
        name=body.name,
        adapter_type=body.adapter_type,
        connection_config_json=body.connection_config,
        credential_ref=encrypted_cred,
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
    user: OptionalAuth = None,
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
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: OptionalAuth = None,
):
    repo = SourceRepository(session)
    updates: dict[str, Any] = {}

    if body.name is not None:
        updates["name"] = body.name
    if body.enabled is not None:
        updates["enabled"] = body.enabled
    if body.default_transfer_id is not None:
        updates["default_transfer_id"] = body.default_transfer_id
    if body.poll_interval is not None:
        updates["poll_interval"] = body.poll_interval
    if body.connection_config is not None:
        updates["connection_config_json"] = body.connection_config
    if body.credential is not None:
        master_key = request.app.state.master_key
        updates["credential_ref"] = _encrypt_credential(body.credential, master_key)

    obj = await repo.update(source_id, **updates)
    if not obj:
        raise HTTPException(status_code=404, detail="Source not found")
    await session.commit()
    return _source_to_dict(obj)


@sources_router.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    user: OptionalAuth = None,
):
    repo = SourceRepository(session)
    await repo.delete(source_id)
    await session.commit()


@sources_router.post("/sources/test-config")
async def test_source_config(
    body: SourceTestRequest,
    request: Request,
    user: OptionalAuth = None,
):
    """Test a source connection config before saving it.

    Does not require an existing source record.
    Returns adapter test_connection() result.
    """
    config = dict(body.connection_config)
    if body.credential:
        config["password"] = body.credential  # Pass plaintext directly for test

    from app.adapters.sources import create_source_adapter
    adapter = create_source_adapter("__test__", body.adapter_type, config)
    result = await adapter.test_connection()
    return result


@sources_router.post("/sources/{source_id}/test")
async def test_source(
    source_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: OptionalAuth = None,
):
    repo = SourceRepository(session)
    obj = await repo.get(source_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Source not found")

    master_key = request.app.state.master_key
    config = _build_adapter_config(obj, master_key)

    from app.adapters.sources import create_source_adapter
    adapter = create_source_adapter(obj.id, obj.adapter_type, config)
    return await adapter.test_connection()


@sources_router.post("/sources/{source_id}/scan")
async def scan_source(
    source_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: OptionalAuth = None,
):
    """Trigger discovery/reconciliation for a source."""
    repo = SourceRepository(session)
    obj = await repo.get(source_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Source not found")

    if hasattr(request.app.state, "supervisor"):
        import asyncio
        asyncio.create_task(request.app.state.supervisor.trigger_scan(source_id))
    else:
        from datetime import datetime, timezone
        await repo.update(source_id, last_scan_at=datetime.now(timezone.utc))
        await session.commit()

    return {"status": "scan_triggered", "source_id": source_id}


@sources_router.post("/sources/{source_id}/complete-onboarding")
async def complete_onboarding(
    source_id: str,
    session: AsyncSession = Depends(get_session),
    user: OptionalAuth = None,
):
    """Activate automatic processing for new items after admin acknowledges baseline."""
    repo = SourceRepository(session)
    obj = await repo.update(source_id, onboarding_state="completed")
    if not obj:
        raise HTTPException(status_code=404, detail="Source not found")
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
    user: OptionalAuth = None,
):
    repo = LabelRuleRepository(session)
    rules = await repo.list_by_source(source_id)
    return [_label_to_dict(r) for r in rules]


@sources_router.post("/sources/{source_id}/labels", status_code=201)
async def create_label(
    source_id: str,
    body: LabelRuleCreate,
    session: AsyncSession = Depends(get_session),
    user: OptionalAuth = None,
):
    source_repo = SourceRepository(session)
    source = await source_repo.get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

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
    user: OptionalAuth = None,
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
    user: OptionalAuth = None,
):
    repo = LabelRuleRepository(session)
    await repo.delete(rule_id)
    await session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _encrypt_credential(plaintext: str, master_key: bytes) -> str:
    """Encrypt a plaintext credential with the master key."""
    from app.security import encrypt_secret
    return "enc:" + encrypt_secret(plaintext, master_key)


def _build_adapter_config(obj: Any, master_key: bytes) -> dict[str, Any]:
    """Build the full adapter config dict by merging non-secret config + decrypted credential."""
    from app.security import decrypt_secret

    config = dict(obj.connection_config_json or {})

    cred_ref = obj.credential_ref or ""
    if cred_ref.startswith("enc:"):
        try:
            plaintext = decrypt_secret(cred_ref[4:], master_key)
            try:
                creds = json.loads(plaintext)
                if isinstance(creds, dict):
                    config.update(creds)
                else:
                    config["password"] = plaintext
            except json.JSONDecodeError:
                config["password"] = plaintext
        except Exception:
            pass
    elif cred_ref:
        try:
            creds = json.loads(cred_ref)
            if isinstance(creds, dict):
                config.update(creds)
        except json.JSONDecodeError:
            config["password"] = cred_ref

    return config


def _source_to_dict(obj: Any) -> dict:
    """Serialize a SourceInstance — never expose credential_ref."""
    return {
        "id": obj.id,
        "name": obj.name,
        "adapter_type": obj.adapter_type,
        "enabled": obj.enabled,
        "connection_config": obj.connection_config_json,  # Non-secret only
        # credential_ref intentionally omitted — only indicate presence
        "has_credential": bool(obj.credential_ref),
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

