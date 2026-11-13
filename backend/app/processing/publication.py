"""Publish prepared files from Path A to Path B.

Rules:
- Select only prepared output files (extracted media or untouched non-archive files)
- Copy to hidden temp sibling inside B (e.g. .Name.publishing-<token>)
- Verify copy integrity (size check)
- Atomic rename within B filesystem
- Collision handling with stable suffix (--<hash8>)
- Never use cross-filesystem rename() directly
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class PublicationResult:
    success: bool
    published_path: str = ""
    published_files: list[str] = field(default_factory=list)
    error: str = ""
    collision_suffix: str = ""


def _sanitize_dirname(name: str) -> str:
    """Sanitize a release name for use as a directory."""
    sanitized = name.replace("/", "_").replace("\\", "_").replace(":", "_")
    sanitized = sanitized.replace("<", "_").replace(">", "_").replace("|", "_")
    sanitized = sanitized.replace("?", "").replace("*", "").replace('"', "_")
    sanitized = sanitized.strip(". ")
    return sanitized[:200]


def _resolve_target_dir(
    completed_dir: str,
    release_name: str,
    existing_ownership: dict[str, str] | None = None,
) -> tuple[Path, str]:
    """Resolve the target directory, handling collisions with stable suffixes.

    Returns (resolved_path, suffix_used).
    """
    base = Path(completed_dir)
    sanitized = _sanitize_dirname(release_name)
    target = base / sanitized

    if not target.exists():
        return target, ""

    # Collision — add stable suffix based on source item hash
    # The caller should pass the source item ID for stability
    # For now, generate a short hash of the name + collision counter
    for attempt in range(100):
        if attempt == 0:
            suffix = ""
        else:
            # Use first 8 chars of hash
            hash_input = f"{release_name}:{attempt}"
            suffix = "--" + hashlib.sha256(hash_input.encode()).hexdigest()[:8]

        candidate = base / (sanitized + suffix)
        if not candidate.exists():
            return candidate, suffix

    raise RuntimeError(f"Could not resolve collision for {sanitized} after 100 attempts")


def publish_files(
    source_dir: Path,
    completed_dir: str,
    release_name: str,
    source_item_hash: str = "",
    archive_files: set[str] | None = None,
) -> PublicationResult:
    """Copy prepared files from source_dir to completed_dir.

    Args:
        source_dir: Path A working directory containing transferred/extracted files
        completed_dir: Path B root
        release_name: Sanitized release name for the target directory
        source_item_hash: Short hash for collision suffix stability
        archive_files: Set of relative paths to exclude (archive parts, SFV, etc.)

    Returns PublicationResult.
    """
    archive_files = archive_files or set()
    result = PublicationResult(success=True)

    # Resolve target directory (handle collisions)
    try:
        target_dir, suffix = _resolve_target_dir(completed_dir, release_name)
    except RuntimeError as e:
        return PublicationResult(success=False, error=str(e))
    result.collision_suffix = suffix

    # Create hidden publishing temp dir in B
    token = secrets.token_hex(4)
    sanitized = _sanitize_dirname(release_name)
    publishing_name = f".{sanitized}.publishing-{token}"
    publishing_dir = Path(completed_dir) / publishing_name

    try:
        publishing_dir.mkdir(parents=True, exist_ok=False)

        # Select files to publish (exclude archives, SFV, sidecar data)
        files_to_publish = []
        for f in source_dir.rglob("*"):
            if not f.is_file():
                continue
            relpath = str(f.relative_to(source_dir))
            ext = f.suffix.lower()

            # Skip archive parts
            if ext in {".rar", ".r00", ".r01", ".r02", ".r03", ".r04", ".r05",
                       ".r06", ".r07", ".r08", ".r09", ".r10", ".r11", ".r12",
                       ".r13", ".r14", ".r15", ".r16", ".r17", ".r18", ".r19",
                       ".r20", ".r21", ".r22", ".r23", ".r24", ".r25",
                       ".r26", ".r27", ".r28", ".r29"}:
                continue
            if ext == ".sfv":
                continue
            # Skip .part files
            if relpath.endswith(".part"):
                continue

            files_to_publish.append((f, relpath))

        # Copy each file
        for src_file, relpath in files_to_publish:
            dst_file = publishing_dir / relpath
            dst_file.parent.mkdir(parents=True, exist_ok=True)

            # Copy with verification
            src_size = src_file.stat().st_size
            shutil.copy2(str(src_file), str(dst_file))
            dst_size = dst_file.stat().st_size

            if src_size != dst_size:
                # Clean up
                shutil.rmtree(str(publishing_dir), ignore_errors=True)
                return PublicationResult(
                    success=False,
                    error=f"Copy verification failed for {relpath}: size mismatch",
                )

            result.published_files.append(relpath)

        # Atomic rename from publishing to final target
        # This is within the same filesystem (both under completed_dir)
        os.rename(str(publishing_dir), str(target_dir))
        result.published_path = str(target_dir)

        logger.info("Published %d files to %s", len(result.published_files), result.published_path)

    except Exception as e:
        # Clean up publishing dir on any error
        shutil.rmtree(str(publishing_dir), ignore_errors=True)
        result.success = False
        result.error = str(e)

    return result
