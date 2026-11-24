"""Test processing modules: verification, extraction, publication, cleanup.

Acceptance criteria:
17. SFV succeeds/fails deterministically; bad checksum retries only necessary files.
18. ZIP, RAR, and multipart RAR extract correctly; dangerous paths rejected.
19. Path A and Path B on separate filesystems publish using verified copy and atomic rename.
20. Two releases with identical sanitized directory names do not overwrite each other.
24. If Library Adapter is null, B is final destination and cleanup removes A but never B.
25. If Library Adapter is configured, successful import is verified before A/B staging cleanup.
"""

from __future__ import annotations

import binascii
import os
import tempfile
from pathlib import Path

import pytest

from app.processing.verification import (
    compute_crc32,
    find_sfv_files,
    parse_sfv,
    verify_files,
)
from app.processing.extraction import (
    detect_archives,
    extract_zip,
    extract_archive,
    _validate_archive_path,
)
from app.processing.cleanup import cleanup_path_a, cleanup_path_b


# ---------------------------------------------------------------------------
# SFV Verification tests
# ---------------------------------------------------------------------------


class TestSFVVerification:
    def test_parse_sfv_basic(self, tmp_path):
        """SFV file is parsed correctly."""
        sfv_content = "; comment line\nfile1.mkv 1A2B3C4D\nfile2.mkv E5F6A7B8\n"
        sfv_path = tmp_path / "test.sfv"
        sfv_path.write_text(sfv_content)

        entries = parse_sfv(sfv_path)
        assert len(entries) == 2
        assert entries[0].filename == "file1.mkv"
        assert entries[0].crc32 == "1A2B3C4D"
        assert entries[1].filename == "file2.mkv"
        assert entries[1].crc32 == "E5F6A7B8"

    def test_compute_crc32(self, tmp_path):
        """CRC32 is computed correctly."""
        data = b"test content"
        expected = f"{binascii.crc32(data) & 0xFFFFFFFF:08X}"
        file_path = tmp_path / "test.bin"
        file_path.write_bytes(data)

        result = compute_crc32(file_path)
        assert result == expected

    def test_verify_files_pass(self, tmp_path):
        """Files with correct CRC32 pass verification."""
        # Create a file
        file_data = b"test content"
        file_path = tmp_path / "file.mkv"
        file_path.write_bytes(file_data)
        crc = f"{binascii.crc32(file_data) & 0xFFFFFFFF:08X}"

        # Create SFV
        sfv_path = tmp_path / "file.sfv"
        sfv_path.write_text(f"file.mkv {crc}\n")
        entries = parse_sfv(sfv_path)

        job_files = [{"remote_relpath": "file.mkv", "size_bytes": len(file_data), "local_relpath": "file.mkv"}]
        result = verify_files(tmp_path, job_files, entries)

        assert len(result.verified) == 1
        assert len(result.failed) == 0
        assert "sfv_crc32" in result.checks_performed
        assert "size_check" in result.checks_performed

    def test_verify_files_crc_mismatch(self, tmp_path):
        """Files with wrong CRC32 fail verification."""
        file_data = b"test content"
        file_path = tmp_path / "file.mkv"
        file_path.write_bytes(file_data)

        # Wrong CRC — use SFVEntry
        from app.processing.verification import SFVEntry
        entries = [SFVEntry(filename="file.mkv", crc32="00000000")]
        job_files = [{"remote_relpath": "file.mkv", "size_bytes": len(file_data), "local_relpath": "file.mkv"}]
        result = verify_files(tmp_path, job_files, entries)

        assert len(result.verified) == 0
        assert len(result.failed) == 1
        assert "CRC32 mismatch" in result.failed[0][1]

    def test_verify_files_size_mismatch(self, tmp_path):
        """Files with wrong size fail verification."""
        file_path = tmp_path / "file.mkv"
        file_path.write_bytes(b"short")

        job_files = [{"remote_relpath": "file.mkv", "size_bytes": 1000, "local_relpath": "file.mkv"}]
        result = verify_files(tmp_path, job_files)

        assert len(result.failed) == 1
        assert "size mismatch" in result.failed[0][1]

    def test_verify_files_no_sfv(self, tmp_path):
        """Without SFV, files are size-only verified."""
        file_path = tmp_path / "file.mkv"
        file_path.write_bytes(b"test")

        job_files = [{"remote_relpath": "file.mkv", "size_bytes": 4, "local_relpath": "file.mkv"}]
        result = verify_files(tmp_path, job_files, None)

        assert len(result.size_only) == 1
        assert len(result.verified) == 0
        assert "sfv_crc32" not in result.checks_performed

    def test_verify_files_missing(self, tmp_path):
        """Missing files are reported."""
        job_files = [{"remote_relpath": "nonexistent.mkv", "size_bytes": 100, "local_relpath": "nonexistent.mkv"}]
        result = verify_files(tmp_path, job_files)

        assert len(result.missing) == 1
        assert "nonexistent.mkv" in result.missing

    def test_find_sfv_files(self, tmp_path):
        """SFV files are discovered."""
        (tmp_path / "test.sfv").write_text("; empty\n")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "another.sfv").write_text("; empty\n")

        sfv_files = find_sfv_files(tmp_path)
        assert len(sfv_files) == 2


# ---------------------------------------------------------------------------
# Archive extraction tests
# ---------------------------------------------------------------------------


class TestExtraction:
    def test_detect_archives_zip(self, tmp_path):
        """ZIP files are detected as archives."""
        import zipfile
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("file.txt", "content")

        archives = detect_archives(tmp_path)
        assert len(archives) == 1
        assert archives[0].suffix == ".zip"

    def test_detect_no_archives(self, tmp_path):
        """Non-archive files are not detected."""
        (tmp_path / "video.mkv").write_bytes(b"fake video")
        archives = detect_archives(tmp_path)
        assert len(archives) == 0

    def test_extract_zip_basic(self, tmp_path):
        """ZIP extraction works for valid files."""
        import zipfile
        zip_path = tmp_path / "test.zip"
        extract_dir = tmp_path / "extracted"

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("file1.txt", "content1")
            zf.writestr("dir/file2.txt", "content2")

        result = extract_zip(zip_path, extract_dir)
        assert result.success
        assert len(result.extracted_files) == 2
        assert (extract_dir / "file1.txt").exists()
        assert (extract_dir / "dir" / "file2.txt").exists()

    def test_extract_zip_rejects_path_traversal(self, tmp_path):
        """ZIP with path traversal is rejected."""
        import zipfile
        zip_path = tmp_path / "malicious.zip"
        extract_dir = tmp_path / "extracted"

        # Create a zip with a path traversal entry
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../../etc/passwd", "malicious")

        result = extract_zip(zip_path, extract_dir)
        assert not result.success
        assert "traversal" in result.error.lower() or "unsafe" in result.error.lower()

    def test_validate_archive_path_rejects_absolute(self, tmp_path):
        """Absolute paths in archives are rejected."""
        with pytest.raises(ValueError):
            _validate_archive_path("/etc/passwd", tmp_path)

    def test_validate_archive_path_rejects_traversal(self, tmp_path):
        """Path traversal is rejected."""
        with pytest.raises(ValueError):
            _validate_archive_path("../../etc/passwd", tmp_path)

    def test_validate_archive_path_rejects_null_byte(self, tmp_path):
        """Null bytes in paths are rejected."""
        with pytest.raises(ValueError, match="Null"):
            _validate_archive_path("file\x00name", tmp_path)

    def test_validate_archive_path_accepts_safe(self, tmp_path):
        """Safe relative paths are accepted."""
        result = _validate_archive_path("dir/file.txt", tmp_path)
        assert result is not None


# ---------------------------------------------------------------------------
# Cleanup tests
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_path_a_removes_temp(self, tmp_path):
        """Path A cleanup removes job temporary files."""
        temp_dir = str(tmp_path / "temp")
        release_dir = tmp_path / "temp" / "Test.Release"
        release_dir.mkdir(parents=True)
        (release_dir / "file.mkv").write_bytes(b"data")

        result = cleanup_path_a(temp_dir, "Test.Release", "job_123")
        assert result.success
        assert result.cleaned_path_a != ""
        assert not release_dir.exists()

    def test_cleanup_path_a_skips_nonexistent(self, tmp_path):
        """Path A cleanup succeeds when directory doesn't exist."""
        result = cleanup_path_a(str(tmp_path / "temp"), "Nonexistent", "job_123")
        assert result.success
        assert result.cleaned_path_a == ""

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks require elevated privileges on Windows")
    def test_cleanup_path_a_rejects_symlink(self, tmp_path):
        """Path A cleanup rejects symlinks."""
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        target = tmp_path / "actual"
        target.mkdir()
        symlink = temp_dir / "Test.Release"
        symlink.symlink_to(target)

        result = cleanup_path_a(str(temp_dir), "Test.Release", "job_123")
        assert not result.success
        assert "symlink" in result.error.lower() or "safety" in result.error.lower()

    def test_cleanup_path_b_no_library_skips(self, tmp_path):
        """Path B is never cleaned when no library is configured."""
        completed_dir = tmp_path / "completed"
        release_dir = completed_dir / "Test.Release"
        release_dir.mkdir(parents=True)
        (release_dir / "file.mkv").write_bytes(b"data")

        result = cleanup_path_b(
            str(completed_dir), "Test.Release", "job_123",
            library_configured=False,
            import_confirmed=False,
        )
        assert result.success
        assert result.skipped_b is True
        assert release_dir.exists()  # Not deleted

    def test_cleanup_path_b_library_unconfirmed_skips(self, tmp_path):
        """Path B is not cleaned when import not confirmed."""
        completed_dir = tmp_path / "completed"
        release_dir = completed_dir / "Test.Release"
        release_dir.mkdir(parents=True)

        result = cleanup_path_b(
            str(completed_dir), "Test.Release", "job_123",
            library_configured=True,
            import_confirmed=False,
        )
        assert result.success
        assert result.skipped_b is True
        assert release_dir.exists()

    def test_cleanup_path_b_library_confirmed_cleans(self, tmp_path):
        """Path B is cleaned when library configured and import confirmed."""
        completed_dir = tmp_path / "completed"
        release_dir = completed_dir / "Test.Release"
        release_dir.mkdir(parents=True)
        (release_dir / "file.mkv").write_bytes(b"data")

        result = cleanup_path_b(
            str(completed_dir), "Test.Release", "job_123",
            library_configured=True,
            import_confirmed=True,
        )
        assert result.success
        assert result.skipped_b is False
        assert result.cleaned_path_b != ""
        assert not release_dir.exists()


def test_cleanup_removes_single_file_items(tmp_path):
    """A single-file release is a file in A and B, not a folder."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "X.mkv").write_bytes(b"v")
    (tmp_path / "b" / "X.mkv").write_bytes(b"v")
    assert cleanup_path_a(str(tmp_path / "a"), "X.mkv", "j").success
    assert cleanup_path_b(str(tmp_path / "b"), "X.mkv", "j", library_configured=True, import_confirmed=True).success
    assert not (tmp_path / "a" / "X.mkv").exists()
    assert not (tmp_path / "b" / "X.mkv").exists()
