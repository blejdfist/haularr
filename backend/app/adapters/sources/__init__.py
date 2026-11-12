"""Source adapter factory."""

from __future__ import annotations

from typing import Any

from app.adapters.sources.base import SourceAdapter
from app.adapters.sources.deluge import DelugeAdapter
from app.adapters.sources.rtorrent import RtorrentAdapter
from app.domain.models import AdapterType


def create_source_adapter(
    source_id: str,
    adapter_type: str,
    config: dict[str, Any],
) -> SourceAdapter:
    """Factory to create a Source Adapter from config."""
    if adapter_type == AdapterType.RTORRENT.value:
        return RtorrentAdapter(
            source_id=source_id,
            xmlrpc_url=config.get("xmlrpc_url", ""),
            username=config.get("username"),
            password=config.get("password"),
            tls_verify=config.get("tls_verify", True),
        )
    elif adapter_type == AdapterType.DELUGE.value:
        return DelugeAdapter(
            source_id=source_id,
            web_url=config.get("web_url", ""),
            password=config.get("password", ""),
            tls_verify=config.get("tls_verify", True),
        )
    else:
        raise ValueError(f"Unknown source adapter type: {adapter_type}")
