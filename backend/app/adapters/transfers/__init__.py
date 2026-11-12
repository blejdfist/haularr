"""Transfer adapter factory."""

from __future__ import annotations

from typing import Any

from app.adapters.transfers.base import TransferAdapter
from app.adapters.transfers.ftps import FTPSAdapter
from app.domain.models import AdapterType


def create_transfer_adapter(
    transfer_id: str,
    adapter_type: str,
    config: dict[str, Any],
) -> TransferAdapter:
    """Factory to create a Transfer Adapter from config."""
    if adapter_type == AdapterType.FTPS.value:
        return FTPSAdapter(
            transfer_id=transfer_id,
            host=config.get("host", ""),
            port=config.get("port", 21),
            username=config.get("username", ""),
            password=config.get("password", ""),
            passive=config.get("passive", True),
            timeout=config.get("timeout", 30),
            tls_verify=config.get("tls_verify", True),
        )
    else:
        raise ValueError(f"Unknown transfer adapter type: {adapter_type}")
