"""Move a downloaded item from the in-progress folder (A) to the completed folder (B).

The item is whatever the source holds under its name, downloaded as-is into A:
- a single file   A/X.mkv  -> B/X.mkv
- a folder        A/Rel/   -> B/Rel/
- a folder with archives: extraction ran in place, so only the files that were
  not downloaded (the extracted ones) move, to B/Rel/. Archives stay in A for cleanup.

Moves are renames on the same drive, copy+delete across drives (shutil.move).
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_EXT = "\\\\?\\"  # the 4 chars \\?\ : Windows extended-length path prefix


def long_path(p: Path | str) -> Path:
    """Extended-length form on Windows, so paths past MAX_PATH (260) work instead of
    failing (WinError 3) or being silently skipped by rglob."""
    p = Path(p)
    if os.name != "nt" or str(p).startswith(_EXT):
        return p
    return Path(_EXT + str(p.resolve()))


def plain_path(p: Path | str) -> str:
    return str(p).removeprefix(_EXT)


@dataclass
class PublicationResult:
    success: bool
    published_path: str = ""
    published_files: list[str] = field(default_factory=list)
    error: str = ""


def publish_item(item: Path, completed_dir: str, downloaded: set[str]) -> PublicationResult:
    """Move ``item`` (file or folder in A) into ``completed_dir``.

    ``downloaded``: paths of the downloaded files relative to A, '/'-separated
    (e.g. ``"Rel/rel.rar"``); used to tell extracted files from downloaded ones.
    """
    from app.processing.extraction import detect_archives

    src, dest_root = long_path(item), long_path(completed_dir)
    target = dest_root / src.name
    result = PublicationResult(success=True, published_path=plain_path(target))

    try:
        if src.is_dir() and detect_archives(src):
            extracted = [
                f for f in sorted(src.rglob("*"))
                if f.is_file() and f.relative_to(src.parent).as_posix() not in downloaded
            ]
            if not extracted:
                if target.exists():  # already moved by an earlier attempt
                    return result
                return PublicationResult(False, error=f"No extracted files in {plain_path(src)}")
            for f in extracted:
                rel = f.relative_to(src)
                dest = target / rel
                if dest.exists():
                    return PublicationResult(False, error=f"{plain_path(dest)} already exists")
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest))
                result.published_files.append(rel.as_posix())
        elif src.exists():
            if target.exists():
                return PublicationResult(False, error=f"{plain_path(target)} already exists")
            dest_root.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(target))
            result.published_files.append(src.name)
        elif not target.exists():
            return PublicationResult(False, error=f"Not found: {plain_path(src)}")
        # else: src gone, target present -> moved by an earlier attempt
    except OSError as e:
        return PublicationResult(False, error=str(e))

    logger.info("Published %s", result.published_path)
    return result
