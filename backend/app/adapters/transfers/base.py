"""Transfer Adapter protocol contract."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from app.domain.models import RemoteFileDTO, RemoteManifest, TransferResult, SourceItemDTO


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
    ) -> RemoteManifest:
        """Confirm which files are available on the remote endpoint and their sizes."""
        ...

    async def transfer_file(
        self,
        remote_file: RemoteFileDTO,
        destination_part_path: str,
        resume_offset: int,
        progress_callback: Callable[[int, int], None] | None,
        cancellation_token: Any | None,
    ) -> TransferResult:
        """Transfer a single file, supporting resume from offset."""
        ...
