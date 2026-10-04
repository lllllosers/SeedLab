"""Offline importer guards and real fixed-workbook transaction failure injection."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import sys
from uuid import uuid4

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/maintenance"))
import legacy_production_import as importer
from test_legacy_backfill import source_path, source_data, temporary_target


@pytest.fixture
def target(temporary_target, tmp_path, monkeypatch):
    database, owner_id = temporary_target
    root = tmp_path / "ProductionData"
    for relative in ("data", "config", "logs", "backups/manual", "backups/auto", "backups/before-upgrade"):
        (root / relative).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(database, root / "data/seedlab.db")
    with closing(sqlite3.connect(root / "data/seedlab.db")) as db:
        db.execute("UPDATE users SET is_admin=1")
        db.commit()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from control_center.config_store import DeploymentSettings
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    settings = DeploymentSettings(port=port)
    (root / "config/seedlab.json").write_text(json.dumps(settings.to_dict()), encoding="utf8")
    (root / "config/instance.json").write_text(json.dumps({"schema_version": 1,
        "instance_id": str(uuid4()), "probe_token": "test-only-identity-" + "x"*32}), encoding="utf8")
    # Only the location policy is replaced for disposable fixtures; all real
    # structure, SQLite, lock, identity, backup and transaction checks remain.
    monkeypatch.setattr(importer, "validate_production_location", lambda root: None)
    return root, root / "data/seedlab.db", settings


def args_for(target, source_path, tmp_path, *, apply=False):
    return ["--source", str(source_path), "--data-root", str(target[0]), "--owner", "legacy-test-owner",
            "--output-dir", str(tmp_path / ("report-" + uuid4().hex))] + (["--apply", "--confirm", importer.CONFIRM] if apply else [])


def state(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        return {table: db.execute(f'SELECT * FROM {table} ORDER BY id').fetchall()
                for table in (*importer.core.BUSINESS_TABLES, "users", "sessions", "audit_logs")}


def test_location_policy_and_invalid_root(tmp_path):
    with pytest.raises(ValueError, match="临时目录"):
        importer.validate_production_location(tmp_path)
    with pytest.raises(ValueError):
        importer.identify_root(Path("relative"))
    with pytest.raises(ValueError):
        importer.identify_root(tmp_path)


def test_excel_structure_error(tmp_path, monkeypatch):
    path = tmp_path / "invalid.xlsx"
    Workbook().save(path)
    monkeypatch.setattr(importer.core, "SOURCE_SHA256", importer.sha256(path))
    with pytest.raises(ValueError, match="工作表不完整"):
        importer.core.read_source(path)


def test_wrong_source_no_database_access(tmp_path, capsys):
    source = tmp_path / "wrong.xlsx"
    source.write_bytes(b"not original")
    assert importer.main(["--source", str(source), "--data-root", str(tmp_path / "missing"), "--owner", "nobody"]) == 1
    assert "SHA256" in capsys.readouterr().err
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("failure", ["identity", "config", "missing_db", "schema", "revision", "integrity", "owner", "inactive", "no_admin", "business"])
def test_target_guards(target, failure):
    root, path, _ = target
    if failure == "identity":
        (root / "config/instance.json").write_text('{}')
    elif failure == "config":
        (root / "config/seedlab.json").write_text('{}')
    elif failure == "missing_db":
        path.unlink()
    elif failure == "integrity":
        path.write_bytes(b"not sqlite")
    else:
        with closing(sqlite3.connect(path)) as db:
            statement = {"schema": "ALTER TABLE users ADD COLUMN unsupported TEXT",
                "revision": "UPDATE alembic_version SET version_num='future'",
                "owner": "UPDATE users SET username='other'", "inactive": "UPDATE users SET is_active=0",
                "no_admin": "UPDATE users SET is_admin=0",
                "business": "INSERT INTO import_jobs(id,created_at,filename,status,total_rows,successful_rows) VALUES('job','2026-10-04','prior','completed',0,0)"}[failure]
            db.execute(statement)
            db.commit()
    before = path.read_bytes() if path.exists() else None
    with pytest.raises((ValueError, sqlite3.Error)):
        path, _ = importer.identify_root(root)
        importer.inspect_target(path, "legacy-test-owner")
    assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.parametrize("kind", ["port", "wal", "idle_reader", "write_lock"])
def test_running_service_and_connections_rejected(target, kind):
    _, path, settings = target
    resource = None
    try:
        if kind == "port":
            resource = socket.socket()
            resource.bind((settings.bind_host, settings.port))
            resource.listen()
        elif kind == "wal":
            Path(str(path) + "-wal").write_bytes(b"active")
        else:
            resource = sqlite3.connect(path)
            resource.execute("SELECT * FROM users").fetchall()
            if kind == "write_lock":
                resource.execute("BEGIN IMMEDIATE")
        with pytest.raises(ValueError, match="停止服务"):
            with importer.stopped_service(path, settings):
                pytest.fail("must not enter")
    finally:
        if resource:
            resource.close()


def test_dry_run_zero_writes(target, source_path, tmp_path, capsys):
    root, path, _ = target
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert importer.main(args_for(target, source_path, tmp_path)) == 0
    assert "zero_database_writes" in capsys.readouterr().out
    assert {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()} == before


def test_apply_confirmation_required(target, source_path, tmp_path):
    argv = args_for(target, source_path, tmp_path)
    assert importer.main(argv + ["--apply"]) == 1
    assert importer.main(argv + ["--apply", "--confirm", "wrong"]) == 1
    assert not list((target[0] / "backups").rglob('*.db'))


def test_backup_failure_blocks_transaction(target, source_path, tmp_path, monkeypatch):
    before = state(target[1])
    monkeypatch.setattr(importer, "snapshot", lambda *a: (_ for _ in ()).throw(OSError("backup failure")))
    assert importer.main(args_for(target, source_path, tmp_path, apply=True)) == 1
    assert state(target[1]) == before


@pytest.mark.parametrize("failure", ["insertion", "database", "workbook", "tasks", "post_tasks", "post_backup", "report"])
def test_atomic_failure_and_postcommit_recovery(target, source_path, tmp_path, monkeypatch, failure):
    before = state(target[1])
    def fail(*args, **kwargs):
        raise ValueError('injected maintenance failure')
    if failure == "insertion":
        original = importer.core.insert_legacy
        def fail_after_insert(*a, **kw):
            original(*a, **kw)
            fail()
        monkeypatch.setattr(importer.core, "insert_legacy", fail_after_insert)
    elif failure in ("database", "workbook"):
        monkeypatch.setattr(importer.core, 'reconcile_' + failure, fail)
    elif failure == "tasks":
        monkeypatch.setattr(importer, "reconcile_tasks", fail)
    elif failure == "post_tasks":
        original = importer.reconcile_tasks
        calls = []
        def fail_after_commit(*a):
            calls.append(1)
            return fail() if len(calls) == 2 else original(*a)
        monkeypatch.setattr(importer, "reconcile_tasks", fail_after_commit)
    elif failure == "report":
        monkeypatch.setattr(importer, "write_reports", fail)
    else:
        original = importer.snapshot
        monkeypatch.setattr(importer, "snapshot", lambda p, r, phase: fail() if phase == 'post-import' else original(p,r,phase))
    assert importer.main(args_for(target, source_path, tmp_path, apply=True)) == 1
    assert state(target[1]) == before
    assert len(list((target[0] / 'backups/manual').glob('*pre-import*.db'))) == 1


@pytest.mark.parametrize('change_at', [2,3])
def test_source_change_before_or_after_commit_recovers(target, source_path, tmp_path, monkeypatch, change_at):
    before = state(target[1])
    original = importer.sha256
    calls = []
    def changing_hash(path):
        if Path(path) == source_path:
            calls.append(1)
            if len(calls) >= change_at:
                return '0'*64
        return original(path)
    monkeypatch.setattr(importer, 'sha256', changing_hash)
    assert importer.main(args_for(target, source_path, tmp_path, apply=True)) == 1
    assert state(target[1]) == before
    assert original(source_path) == importer.core.SOURCE_SHA256


def test_success_facts_backups_and_duplicate_rejection(target, source_path, source_data, tmp_path, capsys):
    argv = args_for(target, source_path, tmp_path, apply=True)
    before_hash = importer.sha256(source_path)
    assert importer.main(argv) == 0
    report = json.loads((Path(argv[argv.index('--output-dir')+1]) / 'legacy-import-report.json').read_text(encoding='utf8'))
    assert report['final_result'] == 'PASS'
    assert report['database']['value_differences'] == report['workbook']['value_differences'] == 0
    assert report['workbook']['wide_rows'] == 2000 and report['workbook']['long_rows'] == 6000
    assert report['workbook']['root_zeros'] == 6 and report['workbook']['shoot_zeros'] == 283
    assert report['workbook']['all_dag_empty_actual_rows'] == 10
    assert report['workbook']['unmeasured_actual_slots'] == 40
    assert report['task_semantics_after_commit']['pending_count'] == 0
    for phase in ('pre_backup','post_backup'):
        backup = report[phase]
        assert importer.sha256(backup['path']) == backup['sha256']
        assert Path(backup['path']).stat().st_size == backup['size']
        with closing(sqlite3.connect(backup['path'])) as db:
            assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    with closing(sqlite3.connect(target[1])) as db:
        assert db.execute('SELECT code,status,ended_at FROM experiments').fetchall() == [('GER-202608-001','completed',None)]
        assert db.execute('SELECT count(*) FROM germination_observations').fetchone()[0] == 0
    assert importer.sha256(source_path) == before_hash == importer.core.SOURCE_SHA256
    saved = state(target[1])
    assert importer.main(args_for(target, source_path, tmp_path)) == 1
    assert importer.main(args_for(target, source_path, tmp_path, apply=True)) == 1
    assert state(target[1]) == saved
    assert '已经存在业务数据' in capsys.readouterr().err
