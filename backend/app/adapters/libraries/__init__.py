"""Library adapter factory."""

from __future__ import annotations

from typing import Any

from app.adapters.libraries.base import LibraryAdapter
from app.adapters.libraries.radarr import RadarrAdapter
from app.adapters.libraries.sonarr import SonarrAdapter
from app.domain.models import AdapterType


def create_library_adapter(
    library_id: str,
    adapter_type: str,
    base_url: str,
    api_key: str,
    config: dict[str, Any] | None = None,
) -> LibraryAdapter:
    """Factory to create a Library Adapter from config."""
    config = config or {}
    tls_verify = config.get("tls_verify", True)

    if adapter_type == AdapterType.SONARR.value:
        return SonarrAdapter(
            library_id=library_id,
            base_url=base_url,
            api_key=api_key,
            tls_verify=tls_verify,
        )
    elif adapter_type == AdapterType.RADARR.value:
        return RadarrAdapter(
            library_id=library_id,
            base_url=base_url,
            api_key=api_key,
            tls_verify=tls_verify,
        )
    else:
        raise ValueError(f"Unknown library adapter type: {adapter_type}")
