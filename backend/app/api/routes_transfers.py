"""Transfer instances and endpoints endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import TransferRepository
from app.security import RequireAuth

transfers_router = APIRouter(tags=["transfers"])


async def get_session(request: Request):
    from app.database.session import get_session_factory
    from app.settings import Settings
    settings: Settings = request.app.state.settings
    factory = get_session_factory(settings)
    async with factory() as session:
        yield session


class TransferCreate(BaseModel):
    name: str
    adapter_type: str = "ftps"
    config: dict[str, Any] = {}
    enabled: bool = True


class TransferUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class EndpointCreate(BaseModel):
    name: str
    priority: int = 0
    host: str
    port: int = 21
    tls_settings: dict[str, Any] = {}
    credential_ref: str
    path_mappings: list[dict[str, str]] = []


@transfers_router.get("/transfers")
async def list_transfers(session: AsyncSession = Depends(get_session)):
    repo = TransferRepository(session)
    items = await repo.list_all()
    return [_transfer_to_dict(t) for t in items]


@transfers_router.post("/transfers", status_code=201)
async def create_transfer(body: TransferCreate, session: AsyncSession = Depends(get_session)):
    repo = TransferRepository(session)
    obj = await repo.create(
        name=body.name,
        adapter_type=body.adapter_type,
        config_json=body.config,
        enabled=body.enabled,
    )
    await session.commit()
    return _transfer_to_dict(obj)


@transfers_router.get("/transfers/{transfer_id}")
async def get_transfer(transfer_id: str, session: AsyncSession = Depends(get_session)):
    repo = TransferRepository(session)
    obj = await repo.get(transfer_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Transfer not found")
    return _transfer_to_dict(obj)


@transfers_router.patch("/transfers/{transfer_id}")
async def update_transfer(
    transfer_id: str, body: TransferUpdate, session: AsyncSession = Depends(get_session)
):
    repo = TransferRepository(session)
    updates = body.model_dump(exclude_none=True)
    if "config" in updates:
        updates["config_json"] = updates.pop("config")
    obj = await repo.update(transfer_id, **updates)
    if not obj:
        raise HTTPException(status_code=404, detail="Transfer not found")
    await session.commit()
    return _transfer_to_dict(obj)


@transfers_router.delete("/transfers/{transfer_id}", status_code=204)
async def delete_transfer(transfer_id: str, session: AsyncSession = Depends(get_session)):
    repo = TransferRepository(session)
    obj = await repo.get(transfer_id)
    if obj:
        await session.delete(obj)
        await session.commit()


@transfers_router.post("/transfers/{transfer_id}/endpoints", status_code=201)
async def add_endpoint(
    transfer_id: str, body: EndpointCreate, session: AsyncSession = Depends(get_session)
):
    repo = TransferRepository(session)
    transfer = await repo.get(transfer_id)
    if not transfer:
        raise HTTPException(status_code=404, detail="Transfer not found")
    endpoint = await repo.add_endpoint(
        transfer_id=transfer_id,
        name=body.name,
        priority=body.priority,
        host=body.host,
        port=body.port,
        tls_settings_json=body.tls_settings,
        credential_ref=body.credential_ref,
        path_mappings_json=body.path_mappings,
    )
    await session.commit()
    return _endpoint_to_dict(endpoint)


@transfers_router.post("/transfers/{transfer_id}/test")
async def test_transfer(
    transfer_id: str, request: Request, session: AsyncSession = Depends(get_session)
):
    repo = TransferRepository(session)
    obj = await repo.get(transfer_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Transfer not found")

    import json
    from app.adapters.transfers import create_transfer_adapter
    from app.security import decrypt_secret

    master_key = request.app.state.master_key
    config = dict(obj.config_json)
    for key in ("password",):
        if key in config and isinstance(config[key], str) and config[key].startswith("enc:"):
            config[key] = decrypt_secret(config[key][4:], master_key)

    adapter = create_transfer_adapter(obj.id, obj.adapter_type, config)
    result = await adapter.test_connection()
    return result


def _redact_config(config: dict) -> dict:
    """Redact password-like fields from config dict."""
    if not isinstance(config, dict):
        return config
    redacted = dict(config)
    sensitive_keys = {"password", "api_key", "apikey", "secret", "token", "credential"}
    for key in list(redacted.keys()):
        if any(s in key.lower() for s in sensitive_keys):
            redacted[key] = "***REDACTED***"
    return redacted


def _transfer_to_dict(obj: Any) -> dict:
    # Safely access endpoints without triggering lazy loading
    try:
        endpoints = list(obj.endpoints) if "endpoints" not in inspect(obj).unloaded else []
    except Exception:
        endpoints = []
    return {
        "id": obj.id,
        "name": obj.name,
        "adapter_type": obj.adapter_type,
        "config": _redact_config(obj.config_json),
        "enabled": obj.enabled,
        "endpoints": [_endpoint_to_dict(e) for e in endpoints],
    }


def _endpoint_to_dict(obj: Any) -> dict:
    return {
        "id": obj.id,
        "transfer_id": obj.transfer_id,
        "name": obj.name,
        "priority": obj.priority,
        "host": obj.host,
        "port": obj.port,
        "tls_settings": obj.tls_settings_json,
        "credential_ref": "***" if obj.credential_ref else None,
        "path_mappings": obj.path_mappings_json,
    }
