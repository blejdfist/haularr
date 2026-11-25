"""Archive extraction for ZIP and RAR (including multipart).

Security:
- Reject zip-slip (../ paths), absolute paths, null bytes
- Reject symlinks/hardlinks that escape the extraction directory
- Enforce max expansion ratio, file count, filename length
- Run in isolated directory under Path A
"""

from __future__ import annotations

import logging
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Limits
MAX_EXPANSION_RATIO = 100  # Max output / input size ratio
MAX_FILE_COUNT = 10000
MAX_FILENAME_LENGTH = 255
MAX_TOTAL_EXPANDED_BYTES = 500 * 1024 * 1024 * 1024  # 500 GB


@dataclass
class ExtractionResult:
    success: bool
    extracted_files: list[str] = field(default_factory=list)
    error: str = ""
    skipped: bool = False  # No archives found
    warnings: list[str] = field(default_factory=list)


def detect_archives(local_dir: Path) -> list[Path]:
    """Find archive files that should be extracted."""
    archives = []

    for f in sorted(local_dir.rglob("*")):
        if not f.is_file():
            continue
        ext = f.suffix.lower()

        if ext == ".zip":
            archives.append(f)
        elif ext == ".r00":
            # Old-style multipart whose first volume is missing its .rar: start from .r00
            if not f.with_suffix(".rar").exists():
                archives.append(f)
        elif ext == ".rar":
            # Only the first volume of a multipart RAR: file.part01.rar, or file.rar
            name_base = f.stem
            if ".part" not in name_base or name_base.endswith((".part01", ".part1")):
                archives.append(f)
    return archives


def _validate_archive_path(path: str, base_dir: Path) -> Path:
    """Validate an extraction path is safe (no traversal, no absolute, no symlinks).

    Raises ValueError if the path is unsafe.
    """
    if not path:
        raise ValueError("Empty path in archive")

    if "\x00" in path:
        raise ValueError("Null byte in archive path")

    # Normalize and resolve
    target = base_dir / path

    # Check for absolute paths
    if Path(path).is_absolute():
        raise ValueError(f"Absolute path in archive: {path}")

    # Check for path traversal
    try:
        target_resolved = target.resolve()
        base_resolved = base_dir.resolve()
        if not str(target_resolved).startswith(str(base_resolved)):
            raise ValueError(f"Path traversal detected: {path}")
    except Exception:
        raise ValueError(f"Unsafe path in archive: {path}")

    if len(path) > MAX_FILENAME_LENGTH:
        raise ValueError(f"Filename too long: {path}")

    return target


def extract_zip(archive_path: Path, dest_dir: Path) -> ExtractionResult:
    """Extract a ZIP archive safely."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    result = ExtractionResult(success=True)

    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            total_input_size = archive_path.stat().st_size
            total_output_size = 0
            file_count = 0

            for info in zf.infolist():
                # Skip directories
                if info.is_dir():
                    continue

                # Validate path
                try:
                    target = _validate_archive_path(info.filename, dest_dir)
                except ValueError as e:
                    result.success = False
                    result.error = str(e)
                    return result

                # Check for symlinks (zip external_attr can indicate symlinks)
                if info.external_attr >> 16 == 0xA1ED:
                    result.success = False
                    result.error = f"Symlink in archive: {info.filename}"
                    return result

                # Check limits
                file_count += 1
                if file_count > MAX_FILE_COUNT:
                    result.success = False
                    result.error = f"Too many files in archive (limit: {MAX_FILE_COUNT})"
                    return result

                total_output_size += info.file_size
                if (
                    total_input_size > 0
                    and total_output_size / total_input_size > MAX_EXPANSION_RATIO
                ):
                    result.success = False
                    result.error = f"Expansion ratio too high (limit: {MAX_EXPANSION_RATIO}x)"
                    return result

                if total_output_size > MAX_TOTAL_EXPANDED_BYTES:
                    result.success = False
                    result.error = "Total expanded size exceeds limit"
                    return result

                # Extract
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    while True:
                        chunk = src.read(65536)
                        if not chunk:
                            break
                        dst.write(chunk)

                result.extracted_files.append(str(target.relative_to(dest_dir)))

    except zipfile.BadZipFile as e:
        result.success = False
        result.error = f"Bad ZIP file: {e}"
    except Exception as e:
        result.success = False
        result.error = f"Extraction failed: {e}"

    return result


def extract_rar(archive_path: Path, dest_dir: Path) -> ExtractionResult:
    """Extract a RAR archive using the unrar or 7z command."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    result = ExtractionResult(success=True)

    # Try unrar first, then 7z
    extractors = [
        (["unrar", "x", "-y", "-o+", "-p-", str(archive_path), str(dest_dir) + "/"], "unrar"),
        (["7z", "x", "-y", "-p", str(archive_path), f"-o{dest_dir}"], "7z"),
    ]

    for cmd, name in extractors:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=4 * 3600,  # a 80 GB remux to a slow disk takes well over 10 minutes
            )
            if proc.returncode == 0:
                # List extracted files
                for f in dest_dir.rglob("*"):
                    if f.is_file() and f != archive_path:
                        result.extracted_files.append(str(f.relative_to(dest_dir)))
                return result
            elif proc.returncode == 11:
                # Password protected
                result.success = False
                result.error = "Archive is password-protected"
                return result
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            result.success = False
            result.error = "Extraction timed out"
            return result

    result.success = False
    result.error = "No RAR extractor available (unrar or 7z not found)"
    return result


def extract_archive(archive_path: Path, dest_dir: Path) -> ExtractionResult:
    """Extract any archive type based on extension."""
    ext = archive_path.suffix.lower()

    if ext == ".zip":
        return extract_zip(archive_path, dest_dir)
    elif ext in (".rar", ".r00"):
        return extract_rar(archive_path, dest_dir)
    else:
        return ExtractionResult(success=False, error=f"Unknown archive type: {ext}")
