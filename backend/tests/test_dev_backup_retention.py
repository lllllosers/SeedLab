"""Backup retention must never remove snapshots or affect reset atomicity."""
import os
from contextlib import closing
from pathlib import Path
import sqlite3

from app.services import dev_reset
from test_measurement_workflow_and_lifecycle import fixture_engine


def seed_backups(tmp_path, count=5):
    directory = tmp_path / "backups"
    directory.mkdir()
    paths = []
    for index in range(count):
        path = directory / f"dev-reset-20261001-00000{index}-test.db"
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE marker(value INTEGER)")
            db.execute("INSERT INTO marker VALUES (?)", (index,))
        os.utime(path, (100 + index, 100 + index))
        paths.append(path)
    return directory, paths


def test_retention_keeps_latest_three_valid_backups_and_all_other_files(tmp_path, capsys):
    directory, paths = seed_backups(tmp_path)
    protected = [directory / name for name in (
        "stage3-final-acceptance-20261001.db", "manual.db", "production.db",
        "dev-reset-invalid.db", "dev-reset-sidecar.db")]
    for path in protected:
        path.write_bytes(b"keep unchanged")
    sidecar = directory / "dev-reset-sidecar.db-wal"
    sidecar.write_bytes(b"pending")
    engine = fixture_engine(tmp_path)
    dev_reset.prune_backups(engine)
    assert not paths[0].exists() and not paths[1].exists()
    assert all(path.exists() for path in paths[2:])
    assert all(path.read_bytes() == b"keep unchanged" for path in protected)
    assert sidecar.read_bytes() == b"pending"
    assert "[PRUNE]" in capsys.readouterr().out
    dev_reset.prune_backups(engine)
    assert all(path.exists() for path in paths[2:])
    engine.dispose()


def test_retention_failure_cannot_fail_successful_reset(auth_client, tmp_path, monkeypatch, capsys):
    _, paths = seed_backups(tmp_path, count=4)
    original = Path.unlink
    def deny_old(path, *args, **kwargs):
        if path == paths[0]:
            raise PermissionError("locked backup")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", deny_old)
    engine = fixture_engine(tmp_path)
    result = dev_reset.reset(engine)
    assert Path(result["backup"]).is_file()
    assert paths[0].is_file()
    assert "[KEEP]" in capsys.readouterr().out
    assert all(count == 0 for table, count in dev_reset.preview(engine).items()
               if table not in dev_reset.PRESERVED)
    engine.dispose()


def test_failed_reset_never_prunes_existing_backups(auth_client, tmp_path, monkeypatch):
    import pytest
    _, paths = seed_backups(tmp_path)
    def fail(_connection):
        raise RuntimeError("simulated reset failure")
    monkeypatch.setattr(dev_reset, "_delete_business", fail)
    engine = fixture_engine(tmp_path)
    with pytest.raises(RuntimeError, match="simulated"):
        dev_reset.reset(engine)
    assert all(path.exists() for path in paths)
    engine.dispose()
