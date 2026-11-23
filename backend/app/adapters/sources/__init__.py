"""Source adapter factory."""

from __future__ import annotations

from typing import Any

from app.adapters.sources.base import SourceAdapter
from app.adapters.sources.rtorrent import RtorrentAdapter
from app.domain.models import AdapterType


def create_source_adapter(
    source_id: str,
    adapter_type: str,
    config: dict[str, Any],
) -> SourceAdapter:
    """Factory to create a Source Adapter from config."""
    if adapter_type == AdapterType.RTORRENT.value:
        return RtorrentAdapter.from_config(source_id, config)
    else:
        raise ValueError(f"Unknown source adapter type: {adapter_type}")
