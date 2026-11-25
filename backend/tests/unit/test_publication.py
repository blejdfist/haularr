"""Publish moves a downloaded item from the in-progress folder to the completed folder.

- single file:          inprogress/X.mkv          -> completed/X.mkv
- folder:               inprogress/Rel/...        -> completed/Rel/...
- folder with archives: only the extracted files  -> completed/Rel/...
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from app.processing.publication import publish_item

LONG = "The.Lord.of.the.Rings.The.Rings.of.Power.S03E04.Gundabad.1080p.AMZN.WEB-DL.DDP5.1.Atmos.H.264-FLUX"


def _x(p: Path) -> Path:
    """Extended-length path, so test fixtures may exceed Windows' MAX_PATH."""
    return Path("\\\\?\\" + str(p)) if os.name == "nt" else p


@pytest.fixture
def dirs(tmp_path):
    a, b = tmp_path / "inprogress", tmp_path / "completed"
    a.mkdir()
    return a, b


def test_single_file_is_moved(dirs):
    a, b = dirs
    (a / "X.mkv").write_bytes(b"video")
    r = publish_item(a / "X.mkv", str(b), downloaded={"X.mkv"})
    assert r.success, r.error
    assert r.published_path == str(b / "X.mkv")
    assert (b / "X.mkv").read_bytes() == b"video"
    assert not (a / "X.mkv").exists()


def test_folder_is_moved_whole(dirs):
    a, b = dirs
    (a / "Rel" / "Subs").mkdir(parents=True)
    (a / "Rel" / "ep.mkv").write_bytes(b"v")
    (a / "Rel" / "Subs" / "en.srt").write_bytes(b"s")
    r = publish_item(a / "Rel", str(b), downloaded={"Rel/ep.mkv", "Rel/Subs/en.srt"})
    assert r.success, r.error
    assert r.published_path == str(b / "Rel")
    assert (b / "Rel" / "ep.mkv").exists() and (b / "Rel" / "Subs" / "en.srt").exists()
    assert not (a / "Rel").exists()


def test_archive_folder_moves_only_extracted_files(dirs):
    a, b = dirs
    rel = a / "Rel"
    rel.mkdir()
    for name in ("rel.rar", "rel.r00", "rel.sfv", "rel.nfo"):  # downloaded
        (rel / name).write_bytes(b"x")
    (rel / "ep.mkv").write_bytes(b"video")  # extracted in place
    r = publish_item(
        rel, str(b), downloaded={"Rel/rel.rar", "Rel/rel.r00", "Rel/rel.sfv", "Rel/rel.nfo"}
    )
    assert r.success, r.error
    assert r.published_path == str(b / "Rel")
    assert sorted(p.name for p in (b / "Rel").iterdir()) == ["ep.mkv"]
    assert (rel / "rel.rar").exists()  # archives stay for cleanup
    assert not (rel / "ep.mkv").exists()


def test_archive_folder_without_extracted_files_fails(dirs):
    a, b = dirs
    (a / "Rel").mkdir()
    (a / "Rel" / "rel.rar").write_bytes(b"x")
    r = publish_item(a / "Rel", str(b), downloaded={"Rel/rel.rar"})
    assert not r.success
    assert "No extracted files" in r.error


def test_rerun_after_publish_succeeds(dirs):
    a, b = dirs
    (a / "X.mkv").write_bytes(b"video")
    assert publish_item(a / "X.mkv", str(b), downloaded={"X.mkv"}).success
    r = publish_item(a / "X.mkv", str(b), downloaded={"X.mkv"})  # retry after a later crash
    assert r.success, r.error
    assert r.published_path == str(b / "X.mkv")


def test_existing_target_is_not_overwritten(dirs):
    a, b = dirs
    (a / "X.mkv").write_bytes(b"new")
    b.mkdir()
    (b / "X.mkv").write_bytes(b"old")
    r = publish_item(a / "X.mkv", str(b), downloaded={"X.mkv"})
    assert not r.success
    assert "already exists" in r.error
    assert (b / "X.mkv").read_bytes() == b"old"


@pytest.mark.skipif(os.name != "nt", reason="MAX_PATH is a Windows limit")
def test_paths_past_max_path(dirs):
    a, b = dirs
    rel = a / LONG
    _x(rel).mkdir()
    _x(rel / f"{LONG}.rar").write_bytes(b"x")
    _x(rel / f"{LONG}.mkv").write_bytes(b"video")
    assert len(str(b / LONG / f"{LONG}.mkv")) > 260

    r = publish_item(rel, str(b), downloaded={f"{LONG}/{LONG}.rar"})
    assert r.success, r.error
    assert r.published_path == str(b / LONG)  # plain path for the importer
    assert _x(b / LONG / f"{LONG}.mkv").read_bytes() == b"video"
