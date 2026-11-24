"""Migration c5d2a8e41f07 rewrites existing jobs to the renamed stages and statuses."""

from __future__ import annotations

import sqlite3

from alembic import command


def test_stage_rename_migration(settings, monkeypatch):
    from app.main import _alembic_config

    monkeypatch.setenv("HAULARR_CONFIG_DIR", str(settings.config_dir))
    cfg = _alembic_config(settings)
    command.upgrade(cfg, "b4e1f0c2d9a3")

    db = sqlite3.connect(settings.config_dir / "haularr.db")
    now = "2026-01-01 00:00:00"
    jobs = {"j1": "resolve_source", "j2": "download", "j3": "publish", "j4": "confirm_import", "j5": "notify"}
    for job_id, stage in jobs.items():
        db.execute(
            "INSERT INTO jobs (id, source_item_id, rule_id, config_snapshot_json, priority, status, stage,"
            " attempts, created_at, updated_at, download_bytes_total, download_bytes_done)"
            " VALUES (?, ?, 'r', '{}', 0, 'queued', ?, 0, ?, ?, 0, 0)",
            (job_id, f"i{job_id}", stage, now, now),
        )
        db.execute(
            "INSERT INTO stage_runs (id, job_id, stage, attempt, status, progress_json, metadata_json)"
            " VALUES (?, ?, ?, 1, 'succeeded', '{}', '{}')",
            (f"r{job_id}", job_id, stage),
        )
    db.execute(
        "INSERT INTO jobs (id, source_item_id, rule_id, config_snapshot_json, priority, status, stage,"
        " attempts, created_at, updated_at, download_bytes_total, download_bytes_done, error_code)"
        " VALUES ('j6', 'i', 'r', '{}', 0, 'waiting_source', 'download', 0, ?, ?, 0, 0, 'no_transfer_config')",
        (now, now),
    )
    db.commit()
    db.close()

    command.upgrade(cfg, "head")

    db = sqlite3.connect(settings.config_dir / "haularr.db")
    stages = dict(db.execute("SELECT id, stage FROM jobs WHERE id != 'j6'").fetchall())
    parked = db.execute("SELECT status FROM jobs WHERE id = 'j6'").fetchone()[0]
    run_stages = {s for (s,) in db.execute("SELECT stage FROM stage_runs")}
    db.close()

    assert stages == {"j1": "transfer", "j2": "transfer", "j3": "move", "j4": "cleanup", "j5": "cleanup"}
    assert parked == "waiting_transfer"
    assert run_stages == {"transfer", "move"}
