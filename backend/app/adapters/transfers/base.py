"""Transfer Adapter protocol contract."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from app.domain.models import RemoteFileDTO, RemoteManifest, SourceItemDTO, TransferResult


class TransferAdapter(Protocol):
    """Narrow interface that every Transfer Adapter must satisfy."""

    transfer_id: str

    async def test_connection(self) -> dict:
        """Test connectivity; return {'ok': True, ...}."""
        ...

    async def inspect(
        self,
        source_item: SourceItemDTO,
        file_manifest: list[RemoteFileDTO],
        path_mappings: list[dict[str, str]] | None = None,
    ) -> RemoteManifest:
        """Confirm which files are available on the remote endpoint and their sizes."""
        ...

    async def transfer_file(
        self,
        remote_file: RemoteFileDTO,
        remote_base_path: str,
        destination_part_path: str,
        resume_offset: int = 0,
        progress_callback: Callable[[int, int], None] | None = None,
        cancellation_token: Any | None = None,
        path_mappings: list[dict[str, str]] | None = None,
    ) -> TransferResult:
        """Transfer a single file, supporting resume from offset."""
        ...
