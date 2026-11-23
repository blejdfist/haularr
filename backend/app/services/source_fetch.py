"""Source-owned FTP (explicit TLS) fetch config, stored as TransferInstance + TransferEndpoint."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SourceInstance, TransferEndpoint, TransferInstance
from app.security import decrypt_secret, encrypt_secret

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


async def upsert_source_fetch(
    session: AsyncSession, source: SourceInstance, fetch: FetchConfig, master_key: bytes
) -> None:
    """Create or update the source's transfer + primary endpoint. Does not commit."""
    config = {"tls_mode": "explicit", "tls_verify": fetch.tls_verify}
    cred = "enc:" + encrypt_secret(
        json.dumps({"username": fetch.username, "password": fetch.password}), master_key
    )
    mappings = [m.model_dump() for m in fetch.path_mappings]

    transfer = (
        await session.get(TransferInstance, source.default_transfer_id)
        if source.default_transfer_id
        else None
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
            pass
    return {
        "host": ep.host,
        "port": ep.port,
        "username": username,
        "tls_verify": transfer.config_json.get("tls_verify", True),
        "path_mappings": ep.path_mappings_json,
        "has_password": bool(ep.credential_ref),
    }
