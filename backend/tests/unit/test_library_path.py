"""Translate Haularr's local paths into the paths the library (Sonarr/Radarr) sees."""

from app.jobs.runner import _library_path

MAP = [{"local_prefix": r"D:\Temp\haularr\downloads", "library_prefix": "/downloads"}]


def test_windows_path_into_container_path():
    assert (
        _library_path(r"D:\Temp\haularr\downloads\completed\tv\X.mkv", MAP)
        == "/downloads/completed/tv/X.mkv"
    )


def test_prefix_match_ignores_case_and_slash_style():
    assert _library_path("d:/temp/HAULARR/downloads/completed/X", MAP) == "/downloads/completed/X"


def test_prefix_must_end_at_a_folder_boundary():
    p = r"D:\Temp\haularr\downloads-old\X"
    assert _library_path(p, MAP) == p


def test_no_mapping_returns_path_unchanged():
    assert _library_path(r"D:\x\y", []) == r"D:\x\y"
    assert _library_path(r"D:\x\y", None) == r"D:\x\y"
