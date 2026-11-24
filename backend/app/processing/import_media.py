"""Library import: inspect, submit, reconcile.

Uses the Library Adapter protocol:
1. inspect_import — GET ManualImport candidates from Arr
2. submit_import — POST ManualImport command to Arr
3. reconcile_import — check command status + library inventory

Never submit rejected candidates automatically.
Track per-file outcomes.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ImportProcessResult:
    success: bool
    imported_paths: list[str] = field(default_factory=list)
    rejected_paths: list[str] = field(default_factory=list)
    skipped_paths: list[str] = field(default_factory=list)
    pending: bool = False  # Import still running
    error: str = ""


async def run_import_stage(
    library_adapter: Any,
    ready_path: str,
    match: Any,
    timeout: float = 300,
) -> ImportProcessResult:
    """Inspect and submit import for accepted candidates.

    Args:
        library_adapter: LibraryAdapter instance
        ready_path: Path B directory with prepared files
        match: MediaMatch from classification

    Returns ImportProcessResult.
    """
    result = ImportProcessResult(success=False)

    # Step 1: Inspect candidates
    try:
        inspection = await library_adapter.inspect_import(ready_path, match)
    except Exception as e:
        result.error = f"Inspect failed: {e}"
        return result

    # Separate accepted and rejected candidates
    accepted = []
    for candidate in inspection.candidates:
        if candidate.rejection_reasons:
            result.rejected_paths.append(candidate.relative_path)
        else:
            accepted.append(candidate)

    if not accepted:
        if result.rejected_paths:
            result.error = f"All {len(result.rejected_paths)} candidates rejected"
        else:
            result.error = "No import candidates found"
        return result

    # Step 2: Submit import for accepted candidates only
    try:
        operation = await library_adapter.submit_import(accepted)
    except Exception as e:
        result.error = f"Submit failed: {e}"
        return result

    # Step 3: Reconcile. The Arr command is queued at first; wait for it here, since a
    # retry of this stage would re-inspect a folder the Arr has already moved files out of.
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            outcome = await library_adapter.reconcile_import(operation, match)
        except Exception as e:
            result.error = f"Reconcile failed: {e}"
            return result
        if not outcome.details.get("pending") or asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(2)

    if outcome.success:
        result.success = True
        result.imported_paths = outcome.imported_paths
        result.skipped_paths = outcome.skipped_paths
    else:
        # Check if still pending
        if outcome.details.get("pending"):
            result.pending = True
            result.error = "Import still in progress"
        else:
            result.error = f"Import failed: {outcome.details}"

    return result
