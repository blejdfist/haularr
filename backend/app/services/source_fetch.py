"""Source-owned FTP (explicit TLS) fetch config, stored as TransferInstance + TransferEndpoint."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SourceInstance, TransferEndpoint, TransferInstance
from app.security import decrypt_secret, encrypt_secret

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.api.routes_sources import FetchConfig


async def _endpoint(session: AsyncSession, transfer_id: str) -> TransferEndpoint | None:
    res = await session.execute(
        select(TransferEndpoint)
        .where(TransferEndpoint.transfer_id == transfer_id)
        .order_by(TransferEndpoint.priority)
        .limit(1)
    )
    return res.scalar_one_or_none()


async def resolve_password(
    session: AsyncSession, transfer_id: str | None, fetch: FetchConfig, master_key: bytes
) -> str:
    """The given password, or the saved one when blank (editing must not force re-entry)."""
    if fetch.password:
        return fetch.password
    ep = await _endpoint(session, transfer_id) if transfer_id else None
    if ep is None or not ep.credential_ref.startswith("enc:"):
        raise HTTPException(status_code=422, detail="FTP password is required")
    return json.loads(decrypt_secret(ep.credential_ref[4:], master_key))["password"]


async def upsert_source_fetch(
    session: AsyncSession, source: SourceInstance, fetch: FetchConfig, master_key: bytes
) -> None:
    """Create or update the source's transfer + primary endpoint. Does not commit."""
    config = {"tls_mode": "explicit", "tls_verify": fetch.tls_verify}
    mappings = [m.model_dump() for m in fetch.path_mappings]

    transfer = (
        await session.get(TransferInstance, source.default_transfer_id)
        if source.default_transfer_id
        else None
    )
    password = await resolve_password(session, transfer.id if transfer else None, fetch, master_key)
    cred = "enc:" + encrypt_secret(
        json.dumps({"username": fetch.username, "password": password}), master_key
    )
    if transfer is None:
        transfer = TransferInstance(
            name=f"{source.name} FTP", adapter_type="ftps", config_json=config
        )
        session.add(transfer)
        await session.flush()
        source.default_transfer_id = transfer.id
        endpoint = None
    else:
        transfer.config_json = config
        endpoint = await _endpoint(session, transfer.id)

    if endpoint is None:
        endpoint = TransferEndpoint(transfer_id=transfer.id, name="primary", priority=0)
        session.add(endpoint)
    endpoint.host = fetch.host
    endpoint.port = fetch.port
    endpoint.tls_settings_json = {}
    endpoint.credential_ref = cred
    endpoint.path_mappings_json = mappings
    await resume_waiting_jobs(session, source.id, transfer.id)


async def resume_waiting_jobs(session: AsyncSession, source_id: str, transfer_id: str) -> int:
    """Requeue this source's jobs parked for lack of a fetch config. Does not commit."""
    from app.database.models import Job

    jobs = (
        (
            await session.execute(
                select(Job).where(
                    Job.status == "waiting_transfer", Job.error_code == "no_transfer_config"
                )
            )
        )
        .scalars()
        .all()
    )
    n = 0
    for job in jobs:
        if job.config_snapshot_json.get("source_id") != source_id:
            continue
        # JSON column: assign a new dict so the change is detected
        job.config_snapshot_json = {**job.config_snapshot_json, "transfer_id": transfer_id}
        job.status = "queued"
        job.error_code = None
        job.error_detail = None
        n += 1
    return n


async def fetch_to_dict(
    session: AsyncSession, transfer_id: str | None, master_key: bytes
) -> dict | None:
    """Serialize fetch config; never includes the password."""
    if not transfer_id:
        return None
    transfer = await session.get(TransferInstance, transfer_id)
    if transfer is None:
        return None
    ep = await _endpoint(session, transfer_id)
    if ep is None:
        return None
    username = ""
    if ep.credential_ref.startswith("enc:"):
        try:
            username = json.loads(decrypt_secret(ep.credential_ref[4:], master_key)).get(
                "username", ""
            )
        except Exception:
            log.warning("Could not decrypt fetch credentials for transfer %s", transfer_id)
    return {
        "host": ep.host,
        "port": ep.port,
        "username": username,
        "tls_verify": transfer.config_json.get("tls_verify", True),
        "path_mappings": ep.path_mappings_json,
        "has_password": bool(ep.credential_ref),
    }
