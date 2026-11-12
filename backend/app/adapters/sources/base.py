"""Source Adapter protocol contract."""

from __future__ import annotations

from typing import Protocol

from app.domain.models import RemoteFileDTO, SourceItemDTO


class SourceAdapter(Protocol):
    """Narrow interface that every Source Adapter must satisfy."""

    source_id: str

    async def test_connection(self) -> dict:
        """Test connectivity; return {'ok': True, 'version': '...', ...}."""
        ...

    async def list_items(self) -> list[SourceItemDTO]:
        """Return normalized list of all downloads/torrents in this source."""
        ...

    async def get_item(self, item_key: str) -> SourceItemDTO:
        """Return a single normalized item by its remote_id."""
        ...

    async def get_manifest(self, item_key: str) -> list[RemoteFileDTO]:
        """Return the file manifest (paths, sizes, hashes) for an item."""
        ...
