"""Job events reach the application log; the log is mirrored to a size-rotated file."""

from __future__ import annotations

import logging

import pytest

from app.logging_buffer import install_file_handler, remove_file_handler


def test_file_handler_writes_and_rotates(tmp_path):
    path = tmp_path / "logs" / "haularr.log"
    handler = install_file_handler(path, max_bytes=200, backups=2)
    try:
        log = logging.getLogger("app.test.file")
        log.setLevel(logging.INFO)
        for i in range(20):
            log.info("line %d with some padding to fill the file", i)
        handler.flush()
    finally:
        remove_file_handler()
    assert "line 19" in path.read_text(encoding="utf-8")
    assert (tmp_path / "logs" / "haularr.log.1").exists()
    assert not (tmp_path / "logs" / "haularr.log.3").exists()  # only `backups` old files kept


def test_install_file_handler_is_idempotent(tmp_path):
    try:
        a = install_file_handler(tmp_path / "a.log", max_bytes=1000, backups=1)
        b = install_file_handler(tmp_path / "a.log", max_bytes=1000, backups=1)
        assert a is b
        assert logging.getLogger().handlers.count(a) == 1
    finally:
        remove_file_handler()


@pytest.mark.asyncio
async def test_job_events_are_logged(app, settings, caplog):
    from app.database.repositories import JobRepository
    from app.database.session import get_session_factory
    from tests.unit.test_waiting_fetch import _job

    from sqlalchemy import update
    from app.database.models import Job

    _, job_id = await _job(settings)
    title = "Some.Show.S01E01"
    async with get_session_factory(settings)() as session:
        await session.execute(
            update(Job).where(Job.id == job_id).values(config_snapshot_json={"title": title})
        )
        await session.commit()
    with caplog.at_level(logging.INFO, logger="app.jobs.events"):
        async with get_session_factory(settings)() as session:
            await JobRepository(session).add_event(
                job_id=job_id,
                severity="error",
                kind="stage.failed",
                stage="transfer",
                message="Stage download failed permanently: boom",
            )
    [rec] = [r for r in caplog.records if r.name == "app.jobs.events"]
    assert rec.levelno == logging.ERROR
    # Title and id both, so the terminal log is readable and still greppable.
    assert f'"{title}" ({job_id})' in rec.getMessage()
    assert "stage.failed" in rec.getMessage() and "boom" in rec.getMessage()


def test_server_errors_are_captured():
    """uvicorn logs request crashes to 'uvicorn.error'; 'uvicorn' doesn't propagate to root."""
    from app.logging_buffer import install_log_handler, remove_log_handler

    logging.getLogger("uvicorn").propagate = False  # as uvicorn's own logging config sets it
    handler = install_log_handler()
    handler.clear()
    try:
        try:
            a, b = (1, 2, 3)
        except ValueError:
            logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
        [entry] = handler.snapshot()
        assert "too many values to unpack" in entry["exception"]
    finally:
        remove_log_handler()
        logging.getLogger("uvicorn").propagate = True


def test_search_matches_exception_text():
    from app.logging_buffer import LogBufferHandler

    h = LogBufferHandler()
    try:
        a, b = (1, 2, 3)
    except ValueError:
        rec = logging.LogRecord(
            "app.x", logging.ERROR, "", 0, "Job crashed", None, __import__("sys").exc_info()
        )
    h.emit(rec)
    assert len(h.snapshot(search="unpack")) == 1


def test_startup_migrations_keep_log_handlers(tmp_path, monkeypatch):
    """alembic.ini's logging config must not replace the app's handlers (log view, file) or level."""
    from alembic import command

    from app.logging_buffer import install_log_handler, remove_log_handler
    from app.main import _alembic_config
    from app.settings import Settings

    monkeypatch.setenv("HAULARR_CONFIG_DIR", str(tmp_path))
    root = logging.getLogger()
    level = root.level
    handler = install_log_handler()
    try:
        command.upgrade(_alembic_config(Settings(config_dir=tmp_path)), "head")
        assert handler in root.handlers
        assert root.level == level
    finally:
        remove_log_handler()
        root.setLevel(level)
