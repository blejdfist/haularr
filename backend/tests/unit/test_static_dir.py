"""Where the frontend is served from by default."""

from pathlib import Path

from app.settings import default_static_dir


def test_falls_back_to_checkout_build(tmp_path):
    assert default_static_dir(tmp_path) == Path("frontend/build")


def test_prefers_packaged_frontend(tmp_path):
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text("<html></html>")

    assert default_static_dir(tmp_path) == tmp_path / "static"
