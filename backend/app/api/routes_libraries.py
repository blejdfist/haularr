"""Library instances endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import LibraryRepository
from app.security import RequireAuth

libraries_router = APIRouter(tags=["libraries"])


async def get_session(request: Request):
    from app.database.session import get_session_factory
    from app.settings import Settings
    settings: Settings = request.app.state.settings
    factory = get_session_factory(settings)
    async with factory() as session:
        yield session


class LibraryCreate(BaseModel):
    name: str
    adapter_type: str  # "sonarr" | "radarr"
    base_url: str
    api_key_secret_ref: str
    enabled: bool = True
    options: dict[str, Any] = {}


class LibraryUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key_secret_ref: str | None = None
    enabled: bool | None = None
    options: dict[str, Any] | None = None


@libraries_router.get("/libraries")
async def list_libraries(session: AsyncSession = Depends(get_session)):
    repo = LibraryRepository(session)
    items = await repo.list_all()
    return [_library_to_dict(l) for l in items]


@libraries_router.post("/libraries", status_code=201)
async def create_library(body: LibraryCreate, session: AsyncSession = Depends(get_session)):
    repo = LibraryRepository(session)
    obj = await repo.create(
        name=body.name,
        adapter_type=body.adapter_type,
        base_url=body.base_url,
        api_key_secret_ref=body.api_key_secret_ref,
        enabled=body.enabled,
        options_json=body.options,
    )
    await session.commit()
    return _library_to_dict(obj)


@libraries_router.get("/libraries/{library_id}")
async def get_library(library_id: str, session: AsyncSession = Depends(get_session)):
    repo = LibraryRepository(session)
    obj = await repo.get(library_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Library not found")
    return _library_to_dict(obj)


@libraries_router.patch("/libraries/{library_id}")
async def update_library(
    library_id: str, body: LibraryUpdate, session: AsyncSession = Depends(get_session)
):
    repo = LibraryRepository(session)
    updates = body.model_dump(exclude_none=True)
    if "options" in updates:
        updates["options_json"] = updates.pop("options")
    if "api_key_secret_ref" in updates:
        updates["api_key_secret_ref"] = updates.pop("api_key_secret_ref")
    obj = await repo.update(library_id, **updates)
    if not obj:
        raise HTTPException(status_code=404, detail="Library not found")
    await session.commit()
    return _library_to_dict(obj)


@libraries_router.delete("/libraries/{library_id}", status_code=204)
async def delete_library(library_id: str, session: AsyncSession = Depends(get_session)):
    repo = LibraryRepository(session)
    obj = await repo.get(library_id)
    if obj:
        from sqlalchemy import func, select, update
        from app.database.models import FileImport, MediaMatch, SourceLabelRule

        used = await session.scalar(
            select(func.count()).select_from(SourceLabelRule).where(
                SourceLabelRule.library_instance_id == library_id
            )
        )
        if used:
            raise HTTPException(
                status_code=409, detail=f"Library is used by {used} tag mapping(s)"
            )
        # History refs are nullable; keep the rows, drop the link
        for model in (MediaMatch, FileImport):
            await session.execute(
                update(model)
                .where(model.library_instance_id == library_id)
                .values(library_instance_id=None)
            )
        await session.delete(obj)
        await session.commit()


@libraries_router.post("/libraries/{library_id}/test")
async def test_library(
    library_id: str, request: Request, session: AsyncSession = Depends(get_session)
):
    repo = LibraryRepository(session)
    obj = await repo.get(library_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Library not found")

    from app.adapters.libraries import create_library_adapter
    from app.security import decrypt_secret

    master_key = request.app.state.master_key
    api_key = obj.api_key_secret_ref
    if api_key.startswith("enc:"):
        api_key = decrypt_secret(api_key[4:], master_key)

    adapter = create_library_adapter(
        obj.id, obj.adapter_type, obj.base_url, api_key, obj.options_json
    )
    result = await adapter.test_connection()
    return result


def _library_to_dict(obj: Any) -> dict:
    return {
        "id": obj.id,
        "name": obj.name,
        "adapter_type": obj.adapter_type,
        "base_url": obj.base_url,
        "api_key_secret_ref": "***" if obj.api_key_secret_ref else None,
        "enabled": obj.enabled,
        "options": obj.options_json,
    }
