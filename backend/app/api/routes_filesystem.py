"""Read-only browsing of folders on the Haularr server."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["system"])


class DirectoryEntry(BaseModel):
    name: str
    path: str


class DirectoryListing(BaseModel):
    path: str | None
    parent: str | None
    directories: list[DirectoryEntry]


@router.get("/filesystem", response_model=DirectoryListing)
def browse_filesystem(path: str = "") -> DirectoryListing:
    """List server folders; an empty path lists filesystem roots or Windows drives."""
    if not path:
        roots = os.listdrives() if os.name == "nt" else ["/"]
        return DirectoryListing(
            path=None,
            parent=None,
            directories=[DirectoryEntry(name=root, path=root) for root in roots],
        )

    try:
        directory = Path(path)
        if not directory.is_absolute():
            raise HTTPException(400, "Enter an absolute server folder path.")
        directory = directory.resolve(strict=True)
        if not directory.is_dir():
            raise HTTPException(400, "This path is not a folder.")
        entries = []
        with os.scandir(directory) as children:
            for child in children:
                try:
                    if child.is_dir():
                        entries.append(DirectoryEntry(name=child.name, path=child.path))
                except OSError:
                    # A child may disappear or be inaccessible while listing its parent.
                    continue
        entries.sort(key=lambda entry: (entry.name.casefold(), entry.name))
        return DirectoryListing(
            path=str(directory),
            parent=str(directory.parent) if directory.parent != directory else None,
            directories=entries,
        )
    except FileNotFoundError:
        raise HTTPException(
            404, "Folder not found. Enter another path or browse from roots."
        ) from None
    except PermissionError:
        raise HTTPException(
            403, "Haularr does not have permission to browse this folder."
        ) from None
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(
            400, "Unable to browse this path. Enter another server folder."
        ) from None
