"""SFV verification and file integrity checking.

SFV files contain CRC32 checksums for files. Parse them and verify
each referenced file. Also check expected sizes against the Source manifest.

SFV format: one file per line, filename followed by CRC32 in hex.
  filename.ext 1A2B3C4D
  another.ext  E5F6A7B8
Lines starting with ; are comments.
"""

from __future__ import annotations

import binascii
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# SFV line: filename (with optional spaces) + 8-char hex CRC32
_SVF_LINE_RE = re.compile(r"^(.+?)\s+([0-9A-Fa-f]{8})\s*$")


@dataclass
class SFVEntry:
    filename: str
    crc32: str  # 8-char hex


@dataclass
class VerificationResult:
    verified: list[str] = field(default_factory=list)  # Files that passed all checks
    failed: list[tuple[str, str]] = field(default_factory=list)  # (filename, reason)
    missing: list[str] = field(default_factory=list)
    size_only: list[str] = field(default_factory=list)
    verification_unavailable: list[str] = field(default_factory=list)
    checks_performed: list[str] = field(default_factory=list)


def parse_sfv(sfv_path: Path) -> list[SFVEntry]:
    """Parse an SFV file and return list of entries."""
    entries = []
    try:
        content = sfv_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Failed to read SFV %s: %s", sfv_path, exc)
        return entries

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        match = _SVF_LINE_RE.match(line)
        if match:
            filename = match.group(1).strip()
            crc32 = match.group(2).upper()
            entries.append(SFVEntry(filename=filename, crc32=crc32))

    return entries


def compute_crc32(file_path: Path) -> str | None:
    """Compute CRC32 of a file, return as 8-char hex string."""
    try:
        crc = 0
        with open(file_path, "rb") as f:
            while chunk := f.read(8 << 20):  # 8 MiB chunks: release files can be tens of GB
                crc = binascii.crc32(chunk, crc)
        return f"{crc & 0xFFFFFFFF:08X}"
    except Exception as exc:
        logger.warning("CRC32 computation failed for %s: %s", file_path, exc)
        return None


def verify_files(
    local_dir: Path,
    job_files: list[dict],
    sfv_entries: list[SFVEntry] | None = None,
) -> VerificationResult:
    """Verify files in local_dir.

    Args:
        local_dir: Directory containing transferred files
        job_files: List of dicts with remote_relpath, size_bytes, local_relpath
        sfv_entries: Parsed SFV entries (or None if no SFV file exists)

    Returns VerificationResult with per-file outcomes.
    """
    result = VerificationResult()

    # Build map of expected files
    expected_files = {f["remote_relpath"]: f for f in job_files}

    # Build map of SFV entries by filename
    sfv_map: dict[str, str] = {}
    if sfv_entries:
        for entry in sfv_entries:
            # Match by basename — SFV typically uses relative paths
            sfv_map[entry.filename] = entry.crc32
        result.checks_performed.append("sfv_crc32")

    result.checks_performed.append("size_check")

    for relpath, file_info in expected_files.items():
        local_path = local_dir / (file_info.get("local_relpath") or relpath)

        if not local_path.exists():
            result.missing.append(relpath)
            continue

        # Size check
        actual_size = local_path.stat().st_size
        expected_size = file_info.get("size_bytes", 0)
        if actual_size != expected_size:
            result.failed.append(
                (relpath, f"size mismatch: expected {expected_size}, got {actual_size}")
            )
            continue

        # SFV CRC32 check
        if sfv_map:
            # Try to match by basename or full relative path
            crc_expected = sfv_map.get(relpath) or sfv_map.get(local_path.name)
            if crc_expected:
                actual_crc = compute_crc32(local_path)
                if actual_crc is None:
                    result.failed.append((relpath, "CRC32 computation failed"))
                elif actual_crc != crc_expected:
                    result.failed.append(
                        (relpath, f"CRC32 mismatch: expected {crc_expected}, got {actual_crc}")
                    )
                else:
                    result.verified.append(relpath)
            else:
                # No SFV entry for this file — size check only
                result.size_only.append(relpath)
        else:
            # No SFV file at all — size check only
            result.size_only.append(relpath)

    # Check SFV entries that have no corresponding job file
    if sfv_map:
        for sfv_name in sfv_map:
            if sfv_name not in expected_files and Path(sfv_name).name not in [
                Path(f).name for f in expected_files
            ]:
                result.missing.append(sfv_name)

    return result


def find_sfv_files(local_dir: Path) -> list[Path]:
    """Find .sfv files in the given directory."""
    return list(local_dir.rglob("*.sfv"))
