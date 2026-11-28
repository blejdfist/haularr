"""Migrations create the schema expected by the application."""

from pathlib import Path

import app
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from app.database.models import Base
from app.main import _alembic_config
from app.settings import Settings
from sqlalchemy import create_engine, text


def _include_object(obj, name, type_, reflected, compare_to):
    # This historical partial index is deliberately maintained outside ORM metadata.
    return not (type_ == "index" and name == "ix_jobs_one_active_per_item")


def test_fresh_database_matches_models(settings):
    cfg = _alembic_config(settings)
    command.upgrade(cfg, "head")
    engine = create_engine(settings.sync_database_url)
    try:
        with engine.connect() as connection:
            assert (
                compare_metadata(
                    MigrationContext.configure(
                        connection, opts={"include_object": _include_object}
                    ),
                    Base.metadata,
                )
                == []
            )
            index_sql = connection.execute(
                text("SELECT sql FROM sqlite_master WHERE name = 'ix_jobs_one_active_per_item'")
            ).scalar()
            assert isinstance(index_sql, str)
            assert "CREATE UNIQUE INDEX" in index_sql
            assert "WHERE ended_at IS NULL" in index_sql
    finally:
        engine.dispose()


def test_alembic_config_is_self_contained():
    cfg = _alembic_config(Settings())
    package = Path(app.__file__).parent

    assert cfg.config_file_name is None
    assert Path(cfg.get_main_option("script_location")) == package / "migrations"


def test_migrations_use_the_settings_database(tmp_path, monkeypatch):
    env_dir, app_dir = tmp_path / "env", tmp_path / "app % dir"
    app_dir.mkdir()
    monkeypatch.setenv("HAULARR_CONFIG_DIR", str(env_dir))

    command.upgrade(_alembic_config(Settings(config_dir=app_dir)), "head")

    assert (app_dir / "haularr.db").exists()
    assert not env_dir.exists()


def test_command_line_config_upgrades_without_ini_file(tmp_path, monkeypatch):
    # What `uv run alembic upgrade head` loads: pyproject.toml and a missing alembic.ini
    root = Path(app.__file__).parents[2]
    monkeypatch.setenv("HAULARR_CONFIG_DIR", str(tmp_path))

    command.upgrade(Config(root / "alembic.ini", toml_file=root / "pyproject.toml"), "head")

    assert (tmp_path / "haularr.db").exists()
