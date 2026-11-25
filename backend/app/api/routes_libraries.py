"""Libraries: Sonarr/Radarr instances that completed downloads are imported into."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories import LibraryRepository
from app.database.session import get_session

router = APIRouter(tags=["libraries"])


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


class LibraryTestConfig(BaseModel):
    """Test unsaved settings; empty api_key with library_id reuses the stored key."""

    adapter_type: Literal["sonarr", "radarr"]
    base_url: str
    api_key: str = ""
    library_id: str | None = None


def _api_key(obj: Any, master_key: bytes) -> str:
    from app.security import decrypt_secret

    key = obj.api_key_secret_ref
    return decrypt_secret(key[4:], master_key) if key.startswith("enc:") else key


@router.post("/libraries/test-config")
async def test_library_config(
    body: LibraryTestConfig,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Test unsaved library settings. A blank `api_key` with `library_id` uses the saved key."""
    from app.adapters.libraries import create_library_adapter

    api_key = body.api_key
    if not api_key and body.library_id:
        obj = await LibraryRepository(session).get(body.library_id)
        if not obj:
            raise HTTPException(status_code=404, detail="Library not found")
        api_key = _api_key(obj, request.app.state.master_key)
    if not api_key:
        raise HTTPException(status_code=422, detail="API key required")
    adapter = create_library_adapter(
        body.library_id or "test", body.adapter_type, body.base_url, api_key, {}
    )
    return await adapter.test_connection()


@router.get("/libraries")
async def list_libraries(session: AsyncSession = Depends(get_session)):
    """List libraries. API keys are never returned."""
    repo = LibraryRepository(session)
    items = await repo.list_all()
    return [_library_to_dict(l) for l in items]


@router.post("/libraries", status_code=201)
async def create_library(body: LibraryCreate, session: AsyncSession = Depends(get_session)):
    """Create a library. `api_key_secret_ref` carries the API key."""
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


@router.get("/libraries/{library_id}")
async def get_library(library_id: str, session: AsyncSession = Depends(get_session)):
    """Get one library."""
    repo = LibraryRepository(session)
    obj = await repo.get(library_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Library not found")
    return _library_to_dict(obj)


@router.patch("/libraries/{library_id}")
async def update_library(
    library_id: str, body: LibraryUpdate, session: AsyncSession = Depends(get_session)
):
    """Update a library. Omitted fields (including the API key) are kept."""
    repo = LibraryRepository(session)
    updates = body.model_dump(exclude_none=True)
    if "options" in updates:
        updates["options_json"] = updates.pop("options")
    obj = await repo.update(library_id, **updates)
    if not obj:
        raise HTTPException(status_code=404, detail="Library not found")
    await session.commit()
    return _library_to_dict(obj)


@router.delete("/libraries/{library_id}", status_code=204)
async def delete_library(library_id: str, session: AsyncSession = Depends(get_session)):
    """Delete a library. 409 while a tag rule still imports into it."""
    repo = LibraryRepository(session)
    obj = await repo.get(library_id)
    if obj:
        from sqlalchemy import func, select, update
        from app.database.models import FileImport, MediaMatch, SourceLabelRule

        used = await session.scalar(
            select(func.count())
            .select_from(SourceLabelRule)
            .where(SourceLabelRule.library_instance_id == library_id)
        )
        if used:
            raise HTTPException(status_code=409, detail=f"Library is used by {used} tag mapping(s)")
        # History refs are nullable; keep the rows, drop the link
        for model in (MediaMatch, FileImport):
            await session.execute(
                update(model)
                .where(model.library_instance_id == library_id)
                .values(library_instance_id=None)
            )
        await session.delete(obj)
        await session.commit()


@router.post("/libraries/{library_id}/test")
async def test_library(
    library_id: str, request: Request, session: AsyncSession = Depends(get_session)
):
    """Test the saved connection of a library."""
    repo = LibraryRepository(session)
    obj = await repo.get(library_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Library not found")

    from app.adapters.libraries import create_library_adapter

    api_key = _api_key(obj, request.app.state.master_key)
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
