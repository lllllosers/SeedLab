"""Production safety matrix; every database, snapshot and failure stays in tmp_path."""
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

from alembic import command
import pytest

from app.core.config import get_settings
from app.services import database_upgrade as upgrade
from app.services import database_recovery as recovery
from app.services.migrations import migration_config, upgrade_database
from app.services.sqlite_backup import BackupService, check_database
from app.version import VERSION


MIGRATIONS = Path(__file__).resolve().parents[1] / "alembic"
OLD = "c6d91f28a405"
HEAD = "d2e7a46b910c"


@pytest.fixture(autouse=True)
def isolated_server_environment(monkeypatch):
    for key in ("SEEDLAB_ENV", "SEEDLAB_DATABASE_URL", "SEEDLAB_BOOTSTRAP_TOKEN_PATH",
                "SEEDLAB_WEB_ROOT", "SEEDLAB_COOKIE_SECURE", "SEEDLAB_RUNTIME_INFO"):
        value = os.environ.get(key)
        # Record missing keys too: server_entry writes directly to os.environ.
        monkeypatch.setenv(key, value if value is not None else "")
        if value is None:
            monkeypatch.delenv(key)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def url(path):
    return "sqlite:///" + path.as_posix()


def backup_root(path):
    return path.parent.parent / "backups"


@pytest.fixture
def old_database(tmp_path):
    path = tmp_path / "data/seedlab.db"
    path.parent.mkdir()
    config = migration_config(MIGRATIONS)
    config.attributes["database_url"] = url(path)
    command.upgrade(config, OLD)
    return path


@pytest.fixture
def current_database(old_database):
    upgrade_database(url(old_database), MIGRATIONS)
    return old_database


def prepare(path, migrations=MIGRATIONS):
    return upgrade.prepare_database_for_startup(url(path), migrations, backup_root=backup_root(path))


def restored_snapshot(path):
    return prepare(path).snapshot


def copy_migrations(tmp_path, *, old_program=False):
    root = tmp_path / "program-migrations"
    (root / "versions").mkdir(parents=True)
    shutil.copyfile(MIGRATIONS / "env.py", root / "env.py")
    for source in (MIGRATIONS / "versions").glob("*.py"):
        if not old_program or not source.name.startswith(HEAD):
            shutil.copyfile(source, root / "versions" / source.name)
    return root


def fail_at(monkeypatch, path, scenario, tmp_path):
    migrations = MIGRATIONS
    if scenario == "corrupt":
        path.write_bytes(b"closed corrupt database")
    elif scenario == "fk":
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("INSERT INTO seed_lots(id,created_at,code,taxon_id,is_active) "
                               "VALUES('orphan','2026-10-01','LOT-2026-001','missing',1)")
            connection.commit()
    elif scenario == "backup":
        def refused(*args, **kwargs):
            raise OSError("injected backup write failure")
        monkeypatch.setattr(BackupService, "snapshot", refused)
    elif scenario == "snapshot":
        original = BackupService.snapshot
        def wrong_revision(*args, **kwargs):
            result = original(*args, **kwargs)
            with closing(sqlite3.connect(result.path)) as connection:
                connection.execute("UPDATE alembic_version SET version_num='invalid-snapshot'")
                connection.commit()
            return result
        monkeypatch.setattr(BackupService, "snapshot", wrong_revision)
    elif scenario == "migration":
        def partial_failure(*args, **kwargs):
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("UPDATE alembic_version SET version_num='failed-upgrade'")
                connection.commit()
            raise RuntimeError("injected migration failure after a committed change")
        monkeypatch.setattr(upgrade, "upgrade_database", partial_failure)
    elif scenario == "postflight":
        def invalid(*args, **kwargs):
            raise sqlite3.DatabaseError("injected postflight failure")
        monkeypatch.setattr(upgrade, "postflight", invalid)
    elif scenario == "newer":
        upgrade_database(url(path), MIGRATIONS)
        migrations = copy_migrations(tmp_path, old_program=True)
    elif scenario == "unknown":
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("UPDATE alembic_version SET version_num='unrecognized-revision'")
            connection.commit()
    return migrations


def test_current_schema_repeated_startup_does_not_migrate_or_backup(current_database, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Current schema must not migrate or create a migration snapshot")
    monkeypatch.setattr(upgrade, "upgrade_database", unexpected)
    monkeypatch.setattr(BackupService, "snapshot", unexpected)
    before = current_database.read_bytes()
    for _ in range(3):
        result = prepare(current_database)
        assert result.plan.state == "current" and not result.migrated and result.snapshot is None
    assert current_database.read_bytes() == before
    assert not backup_root(current_database).exists()


def test_old_schema_runs_the_complete_protocol_in_order(old_database, monkeypatch):
    events = []
    original_check = upgrade.validate_database
    def checked(path, **kwargs):
        if path == old_database and "postflight" not in events:
            events.append("preflight")
        return original_check(path, **kwargs)
    monkeypatch.setattr(upgrade, "validate_database", checked)
    for owner, name, label in ((BackupService, "snapshot", "backup"),
                               (upgrade, "validate_snapshot", "snapshot-validation"),
                               (upgrade, "upgrade_database", "migration"),
                               (upgrade, "postflight", "postflight")):
        original = getattr(owner, name)
        def wrapped(*args, _original=original, _label=label, **kwargs):
            events.append(_label)
            return _original(*args, **kwargs)
        monkeypatch.setattr(owner, name, wrapped)
    result = prepare(old_database)
    assert events == ["preflight", "backup", "snapshot-validation", "migration", "postflight"]
    assert result.migrated and result.plan.source_revision == OLD
    assert upgrade.read_revision(old_database) == HEAD
    assert upgrade.read_revision(result.snapshot, immutable=True) == OLD
    assert f"from-{OLD}-to-{HEAD}-app-{VERSION}" in result.snapshot.name
    state = json.loads(result.snapshot.with_suffix(".upgrade.json").read_text(encoding="utf-8"))
    assert state["stage"] == "complete" and state["source_revision"] == OLD and state["target_revision"] == HEAD
    assert not list(result.snapshot.parent.glob("*.partial*"))


@pytest.mark.parametrize("scenario,stage", [("corrupt", "preflight"), ("fk", "preflight"),
    ("backup", "backup"), ("snapshot", "snapshot-validation"), ("migration", "migration"),
    ("postflight", "postflight"), ("newer", "guard"), ("unknown", "guard")])
def test_failed_protocol_preserves_database_and_recovery_evidence(old_database, monkeypatch, tmp_path, scenario, stage):
    migrations = fail_at(monkeypatch, old_database, scenario, tmp_path)
    before = old_database.read_bytes()
    with pytest.raises(upgrade.UpgradeError) as caught:
        prepare(old_database, migrations)
    assert caught.value.stage == stage and old_database.is_file()
    snapshots = list((backup_root(old_database) / "before-upgrade").glob("*.db"))
    if scenario in ("snapshot", "migration", "postflight"):
        assert len(snapshots) == 1 and caught.value.snapshot == snapshots[0]
        state = json.loads(snapshots[0].with_suffix(".upgrade.json").read_text(encoding="utf-8"))
        assert state["stage"] == "failed:" + stage and state["source_revision"] == OLD
        assert state["target_revision"] == HEAD and state["failure"]
    else:
        assert not snapshots
    if scenario != "migration" and scenario != "postflight":
        assert old_database.read_bytes() == before
    if scenario == "migration":
        assert upgrade.read_revision(old_database) == "failed-upgrade"
    if scenario == "postflight":
        assert upgrade.read_revision(old_database) == HEAD


@pytest.mark.parametrize("failure", ["multiple-heads", "missing-parent"])
def test_invalid_migration_graph_blocks_before_any_database_change(old_database, tmp_path, failure):
    root = copy_migrations(tmp_path)
    parent = "None" if failure == "multiple-heads" else "'missing-parent'"
    (root / "versions/test-invalid-graph.py").write_text(
        f"revision='test-invalid-graph'\ndown_revision={parent}\ndef upgrade(): pass\n", encoding="utf-8")
    before = old_database.read_bytes()
    with pytest.raises(upgrade.UpgradeError, match="版本链"):
        prepare(old_database, root)
    assert old_database.read_bytes() == before and not backup_root(old_database).exists()


@pytest.mark.parametrize("layout", ["missing-revision", "empty-version", "multiple-versions"])
def test_invalid_database_revision_is_never_guessed(old_database, layout):
    with closing(sqlite3.connect(old_database)) as connection:
        if layout == "missing-revision":
            connection.execute("DROP TABLE alembic_version")
        elif layout == "empty-version":
            connection.execute("DELETE FROM alembic_version")
        else:
            connection.execute("INSERT INTO alembic_version VALUES('other-revision')")
        connection.commit()
    before = old_database.read_bytes()
    with pytest.raises(upgrade.UpgradeError) as caught:
        prepare(old_database)
    assert caught.value.stage == "guard" and old_database.read_bytes() == before
    assert not backup_root(old_database).exists()


@pytest.mark.parametrize("scenario", ["corrupt", "fk", "backup", "snapshot", "migration", "postflight", "newer", "unknown"])
def test_server_never_starts_after_protocol_failure(old_database, monkeypatch, tmp_path, scenario, capsys):
    import app.server_entry as entry
    migrations = fail_at(monkeypatch, old_database, scenario, tmp_path)
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("isolated UI", encoding="utf-8")
    monkeypatch.setenv("SEEDLAB_ENV", "development")
    monkeypatch.setenv("SEEDLAB_DATABASE_URL", url(old_database))
    def forbidden(*args, **kwargs):
        pytest.fail("Failed schema preparation must not create or start the application")
    monkeypatch.setattr(entry, "run_prepared_server", forbidden)
    try:
        assert entry.main(["--database", str(old_database), "--web-root", str(web),
                           "--bootstrap-token", str(tmp_path / "data/bootstrap.token"),
                           "--migration-root", str(migrations)]) == 1
        assert "数据库启动未通过" in capsys.readouterr().out
    finally:
        get_settings.cache_clear()


def test_recovery_requires_confirmation_and_preserves_failed_database(old_database):
    snapshot = restored_snapshot(old_database)
    before = old_database.read_bytes()
    with pytest.raises(upgrade.UpgradeError, match="明确确认"):
        recovery.restore_database(url(old_database), snapshot, MIGRATIONS, backup_root=backup_root(old_database))
    assert old_database.read_bytes() == before
    result = recovery.restore_database(url(old_database), snapshot, MIGRATIONS,
        backup_root=backup_root(old_database), confirm_stopped=True)
    assert result.revision == OLD and upgrade.read_revision(old_database) == OLD
    assert check_database(old_database).valid
    assert (result.preserved / old_database.name).read_bytes() == before
    assert snapshot.exists() and (result.preserved / "recovery.json").is_file()
    assert not list(old_database.parent.glob("*.partial*"))


@pytest.mark.parametrize("condition", ["corrupt", "wrong-revision", "sidecar"])
def test_invalid_recovery_snapshot_never_replaces_database(old_database, condition):
    snapshot = restored_snapshot(old_database)
    if condition == "corrupt":
        snapshot.write_bytes(b"invalid snapshot")
    elif condition == "wrong-revision":
        with closing(sqlite3.connect(snapshot)) as connection:
            connection.execute("UPDATE alembic_version SET version_num='unknown'")
            connection.commit()
    else:
        Path(str(snapshot) + "-wal").write_bytes(b"unclosed snapshot")
    before = old_database.read_bytes()
    with pytest.raises(upgrade.UpgradeError) as caught:
        recovery.restore_database(url(old_database), snapshot, MIGRATIONS,
            backup_root=backup_root(old_database), confirm_stopped=True)
    assert caught.value.stage == "recovery-validation" and old_database.read_bytes() == before


@pytest.mark.parametrize("journal", ["DELETE", "WAL"])
def test_recovery_refuses_active_external_writer(old_database, journal):
    snapshot = restored_snapshot(old_database)
    with closing(sqlite3.connect(old_database)) as writer:
        writer.execute("PRAGMA journal_mode=" + journal)
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(upgrade.UpgradeError, match="其他程序使用"):
            recovery.restore_database(url(old_database), snapshot, MIGRATIONS,
                backup_root=backup_root(old_database), confirm_stopped=True)
        writer.rollback()
    assert upgrade.read_revision(old_database) == HEAD


def test_recovery_preserves_corrupt_database_and_sidecars(old_database):
    snapshot = restored_snapshot(old_database)
    old_database.write_bytes(b"corrupt failed-upgrade database")
    originals = {old_database.name: old_database.read_bytes()}
    for suffix in ("-wal", "-shm", "-journal"):
        item = Path(str(old_database) + suffix)
        item.write_bytes(b"failed evidence " + suffix.encode())
        originals[item.name] = item.read_bytes()
    result = recovery.restore_database(url(old_database), snapshot, MIGRATIONS,
        backup_root=backup_root(old_database), confirm_stopped=True)
    assert {name: (result.preserved / name).read_bytes() for name in originals} == originals
    assert check_database(old_database).valid and upgrade.read_revision(old_database) == OLD
    assert all(not Path(str(old_database) + suffix).exists() for suffix in ("-wal", "-shm", "-journal"))


@pytest.mark.parametrize("failure", ["archive", "publication"])
def test_recovery_io_failure_does_not_silently_overwrite(old_database, monkeypatch, failure):
    snapshot = restored_snapshot(old_database)
    before = old_database.read_bytes()
    original = recovery.os.rename
    def refused(source, target):
        if (failure == "archive" and source == old_database or
                failure == "publication" and ".restore-" in Path(source).name):
            raise OSError("injected offline recovery failure")
        return original(source, target)
    monkeypatch.setattr(recovery.os, "rename", refused)
    with pytest.raises(upgrade.UpgradeError):
        recovery.restore_database(url(old_database), snapshot, MIGRATIONS,
            backup_root=backup_root(old_database), confirm_stopped=True)
    assert old_database.read_bytes() == before and snapshot.exists()


def test_recovery_postflight_failure_keeps_published_database_and_failure_evidence(old_database, monkeypatch):
    snapshot = restored_snapshot(old_database)
    before = old_database.read_bytes()
    original = recovery.validate_snapshot
    def failed_postflight(path, revision):
        if path == old_database:
            raise sqlite3.DatabaseError("injected restored database postflight failure")
        return original(path, revision)
    monkeypatch.setattr(recovery, "validate_snapshot", failed_postflight)
    with pytest.raises(upgrade.UpgradeError) as caught:
        recovery.restore_database(url(old_database), snapshot, MIGRATIONS,
            backup_root=backup_root(old_database), confirm_stopped=True)
    assert caught.value.stage == "recovery" and caught.value.snapshot == snapshot
    assert upgrade.read_revision(old_database) == OLD and check_database(old_database).valid
    archives = list((backup_root(old_database) / "failed-recovery").iterdir())
    assert len(archives) == 1 and (archives[0] / old_database.name).read_bytes() == before
    assert snapshot.is_file() and not list(old_database.parent.glob("*.partial*"))


def test_auto_retention_never_removes_upgrade_manual_or_recovery_evidence(old_database):
    snapshot = restored_snapshot(old_database)
    service = BackupService(backup_root(old_database))
    manual = service.snapshot(old_database).path
    failed = service.snapshot(old_database, "failed-recovery").path
    for _ in range(3):
        service.snapshot(old_database, "auto")
    assert len(service.prune(1)) == 2
    assert all(path.exists() for path in (snapshot, manual, failed))
    assert service.candidates("before-upgrade") == [snapshot]


def test_upgrade_snapshot_collision_keeps_both_recovery_points_recognizable(old_database, monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    from app.services import sqlite_backup
    identities = iter(("a" * 32, "b" * 32, "a" * 32, "c" * 32, "d" * 32))
    monkeypatch.setattr(sqlite_backup, "uuid4", lambda: SimpleNamespace(hex=next(identities)))
    service = BackupService(backup_root(old_database), clock=lambda: datetime(2026, 10, 1, 12))
    arguments = dict(source_revision=OLD, target_revision=HEAD, application_version=VERSION)
    first = service.snapshot(old_database, "before-upgrade", **arguments).path
    before = first.read_bytes()
    second = service.snapshot(old_database, "before-upgrade", **arguments).path
    assert first != second and first.read_bytes() == before
    assert set(service.candidates("before-upgrade")) == {first, second}
    upgrade.validate_snapshot(first, OLD)
    upgrade.validate_snapshot(second, OLD)


@pytest.mark.parametrize("existing", [False, True])
def test_new_empty_database_is_initialized_without_inventing_a_recovery_snapshot(tmp_path, existing):
    path = tmp_path / "data/seedlab.db"
    if existing:
        path.parent.mkdir()
        path.touch()
    result = prepare(path)
    assert result.plan.state == "new" and result.migrated and result.snapshot is None
    assert check_database(path).valid and upgrade.read_revision(path) == HEAD
    assert not backup_root(path).exists()


def test_missing_configured_database_is_never_replaced_with_an_empty_database(tmp_path):
    path = tmp_path / "data/seedlab.db"
    with pytest.raises(upgrade.UpgradeError, match="不见了"):
        upgrade.prepare_database_for_startup(url(path), MIGRATIONS, allow_create=False)
    assert not path.exists() and not backup_root(path).exists()


def test_server_holds_database_lease_until_it_has_stopped(old_database, monkeypatch, tmp_path):
    import app.server_entry as entry
    import uvicorn
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("isolated UI", encoding="utf-8")
    called = []
    def running(*args, **kwargs):
        called.append(True)
        assert upgrade.read_revision(old_database) == HEAD
        snapshot = next((backup_root(old_database) / "before-upgrade").glob("*.db"))
        with pytest.raises(upgrade.UpgradeError) as caught:
            recovery.restore_database(url(old_database), snapshot, MIGRATIONS,
                backup_root=backup_root(old_database), confirm_stopped=True)
        assert caught.value.stage == "busy"
    monkeypatch.setattr(uvicorn, "run", running)
    assert entry.main(["--database", str(old_database), "--web-root", str(web),
                       "--bootstrap-token", str(tmp_path / "data/bootstrap.token"),
                       "--migration-root", str(MIGRATIONS)]) == 0
    assert called == [True]
    with upgrade.database_lease(url(old_database)):
        pass  # Normal stop releases the lease without deleting its stable lock file.


def test_server_recovery_mode_is_explicit_and_never_starts_server(old_database, monkeypatch, tmp_path):
    import app.server_entry as entry
    snapshot = restored_snapshot(old_database)
    def forbidden(*args, **kwargs):
        pytest.fail("Recovery mode must never start a server")
    monkeypatch.setattr(entry, "run_prepared_server", forbidden)
    arguments = ["--database", str(old_database), "--data-root", str(tmp_path),
                 "--migration-root", str(MIGRATIONS), "--recover-from", str(snapshot)]
    assert entry.main(arguments) == 1
    assert upgrade.read_revision(old_database) == HEAD
    assert entry.main(arguments + ["--confirm-stopped"]) == 0
    assert upgrade.read_revision(old_database) == OLD and check_database(old_database).valid


def test_database_lease_blocks_a_second_process(current_database, tmp_path):
    ready = tmp_path / "lease-ready"
    script = "\n".join(["import sys", "from pathlib import Path",
        "from app.services.database_upgrade import database_lease",
        "with database_lease(sys.argv[1]):", "    Path(sys.argv[2]).write_text('ready')",
        "    sys.stdin.readline()"])
    child = subprocess.Popen([sys.executable, "-B", "-c", script, url(current_database), str(ready)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "The isolated lease holder did not become ready"
        with pytest.raises(upgrade.UpgradeError) as caught:
            prepare(current_database)
        assert caught.value.stage == "busy" and not backup_root(current_database).exists()
    finally:
        try:
            child.communicate("stop\n", timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate()
    with upgrade.database_lease(url(current_database)):
        pass
