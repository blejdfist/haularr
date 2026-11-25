"""Library Adapter protocol contract."""

from __future__ import annotations

from typing import Protocol

from app.domain.models import (
    ImportInspection,
    ImportOperation,
    ImportOutcome,
    LibraryInventory,
    MediaMatch,
)


class LibraryAdapter(Protocol):
    """Narrow interface that every Library Adapter must satisfy."""

    library_id: str

    async def test_connection(self) -> dict:
        """Test connectivity; return {'ok': True, 'version': '...', ...}."""
        ...

    async def parse(self, release_name: str) -> MediaMatch:
        """Parse a release name and return a matched catalog identity (if any)."""
        ...

    async def inspect_library(self, match: MediaMatch) -> LibraryInventory:
        """Derive library presence/file state from match.library_record (no HTTP)."""
        ...

    async def inspect_import(self, ready_path: str, match: MediaMatch) -> ImportInspection:
        """Inspect files in Path B for import candidates and rejections."""
        ...

    async def submit_import(self, selected_candidates: list) -> ImportOperation:
        """Submit accepted candidates to Arr for import."""
        ...

    async def reconcile_import(
        self, operation: ImportOperation, match: MediaMatch
    ) -> ImportOutcome:
        """Confirm import outcome by checking library state after operation."""
        ...
