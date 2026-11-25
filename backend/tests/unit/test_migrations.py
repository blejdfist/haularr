"""Migrations create the schema expected by the application."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.database.models import Base
from app.main import _alembic_config
from sqlalchemy import create_engine, text


def _include_object(obj, name, type_, reflected, compare_to):
    # This historical partial index is deliberately maintained outside ORM metadata.
    return not (type_ == "index" and name == "ix_jobs_one_active_per_item")


def test_fresh_database_matches_models(settings, monkeypatch):
    monkeypatch.setenv("HAULARR_CONFIG_DIR", str(settings.config_dir))
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
