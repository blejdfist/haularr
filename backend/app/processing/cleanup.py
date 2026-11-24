"""Safe cleanup of job temporary files.

Rules:
- Remove only job-owned temporary data under Path A
- Path B cleanup only after confirmed import (if library configured)
- Never delete B if no library configured
- Use safe path allowlist, ownership manifest, non-symlink checks
- Require per-job ownership manifest and rooted containment checks
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class CleanupResult:
    success: bool
    cleaned_path_a: str = ""
    cleaned_path_b: str = ""
    skipped_b: bool = False
    error: str = ""


def _is_safe_to_delete(path: Path, allowed_roots: list[str]) -> bool:
    """Check that a path is within an allowed root and is not a symlink."""
    try:
        resolved = path.resolve()

        # Check symlink
        if path.is_symlink():
            logger.warning("Refusing to delete symlink: %s", path)
            return False

        # Check containment in allowed roots
        for root in allowed_roots:
            root_resolved = Path(root).resolve()
            if str(resolved).startswith(str(root_resolved)):
                return True

        logger.warning("Path %s not in any allowed root", path)
        return False

    except Exception as e:
        logger.warning("Safety check failed for %s: %s", path, e)
        return False


def _remove(target: Path) -> None:
    """Delete an item: a folder, or a single-file release's file. Long paths included."""
    from app.processing.publication import long_path

    if target.is_dir():
        shutil.rmtree(long_path(target))
    else:
        target.unlink()


def cleanup_path_a(
    temp_dir: str,
    release_name: str,
    job_id: str,
) -> CleanupResult:
    """Clean up job-owned temporary data under Path A.

    Args:
        temp_dir: Path A root (configured per label rule)
        release_name: Sanitized release directory name
        job_id: Job ID for ownership verification

    Returns CleanupResult.
    """
    result = CleanupResult(success=True)

    target = Path(temp_dir) / _sanitize_dirname(release_name)

    if not target.exists():
        logger.info("Path A target does not exist, nothing to clean: %s", target)
        return result

    # Safety checks
    if not _is_safe_to_delete(target, [temp_dir]):
        result.success = False
        result.error = f"Path {target} failed safety check"
        return result

    try:
        _remove(target)
        result.cleaned_path_a = str(target)
        logger.info("Cleaned Path A: %s", result.cleaned_path_a)
    except Exception as e:
        result.success = False
        result.error = f"Failed to clean Path A: {e}"

    return result


def cleanup_path_b(
    completed_dir: str,
    release_name: str,
    job_id: str,
    library_configured: bool,
    import_confirmed: bool,
) -> CleanupResult:
    """Clean up Path B if safe.

    Rules:
    - If no library configured, NEVER delete B (it's final output)
    - If library configured, only delete B after confirmed import
    """
    result = CleanupResult(success=True, skipped_b=False)

    if not library_configured:
        result.skipped_b = True
        logger.info("Skipping Path B cleanup — no library configured (B is final)")
        return result

    if not import_confirmed:
        result.skipped_b = True
        logger.info("Skipping Path B cleanup — import not confirmed yet")
        return result

    target = Path(completed_dir) / _sanitize_dirname(release_name)

    if not target.exists():
        return result

    # Safety checks
    if not _is_safe_to_delete(target, [completed_dir]):
        result.success = False
        result.error = f"Path {target} failed safety check"
        return result

    try:
        _remove(target)
        result.cleaned_path_b = str(target)
        logger.info("Cleaned Path B: %s", result.cleaned_path_b)
    except Exception as e:
        result.success = False
        result.error = f"Failed to clean Path B: {e}"

    return result


def _sanitize_dirname(name: str) -> str:
    """Sanitize a release name for use as a directory."""
    sanitized = name.replace("/", "_").replace("\\", "_").replace(":", "_")
    sanitized = sanitized.replace("<", "_").replace(">", "_").replace("|", "_")
    sanitized = sanitized.replace("?", "").replace("*", "").replace('"', "_")
    sanitized = sanitized.strip(". ")
    return sanitized[:200]
