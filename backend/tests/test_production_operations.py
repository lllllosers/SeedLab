"""Real isolated SQLite, archive failures and deployment transactions; never the Production Mirror."""
from contextlib import nullcontext, closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import zipfile

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.core.auth import check_password, create_session, hash_password
from app.db.session import make_engine
from app.models import (User, Taxon, SeedLot, Experiment, ExperimentMaterial, MeasurementTimepoint,
                        GerminationDish, GerminationObservation, SeedlingSample, SeedlingMeasurement)
from app.services.admin_recovery import administrators, reset_administrator, schema_information
from app.services.migrations import upgrade_database
from app.services.runtime_identity import deployment_identity
from control_center.config_store import ConfigStore, DeploymentSettings
from production_ops import OperationsError
from production_ops.bootstrap import inspect_legacy, adopt
from production_ops.deployment import CENTER, SERVER, LAUNCHER, UPDATER, DeploymentStore, atomic_json
from production_ops.executor import UpgradeExecutor
from production_ops.launcher import launch_command
from production_ops.package import REQUIRED, inspect_package, extract_package

HEAD = "d2e7a46b910c"
MIGRATIONS = ROOT / "backend/alembic"


def populate_business(database):
    """Nonempty research facts, including planned/actual time, a missing slot, zero and explicit NA."""
    engine = make_engine("sqlite:///" + database.as_posix())
    moment = datetime(2026, 8, 10, 8, tzinfo=timezone.utc)
    with Session(engine) as session, session.begin():
        taxon = Taxon(code="SP-0001", scientific_name="Test species", common_name="隔离验证材料")
        experiment = Experiment(code="GER-202608-001", name="隔离升级保留验证", status="active",
                                planned_start_date=moment.date(), started_at=moment + timedelta(days=1))
        session.add_all([taxon, experiment])
        session.flush()
        lot = SeedLot(code="LOT-2026-001", taxon_id=taxon.id, source_code="original-007")
        timepoint = MeasurementTimepoint(experiment_id=experiment.id, day_after_germination=7)
        session.add_all([lot, timepoint])
        session.flush()
        material = ExperimentMaterial(experiment_id=experiment.id, seed_lot_id=lot.id, experiment_number=1)
        session.add(material)
        session.flush()
        dish = GerminationDish(material_id=material.id, code="internal-001", label="001", replicate_no=1,
                               seed_count=10, sown_at=moment + timedelta(days=1))
        session.add(dish)
        session.flush()
        session.add(GerminationObservation(dish_id=dish.id, observed_at=moment + timedelta(days=2), new_germinated_count=0))
        for number in (1, 2):
            sample = SeedlingSample(dish_id=dish.id, sample_number=number, germinated_at=moment + timedelta(days=3))
            session.add(sample)
            session.flush()
            if number == 1:
                session.add(SeedlingMeasurement(sample_id=sample.id, timepoint_id=timepoint.id, root_length_mm=0,
                    shoot_length_mm=None, shoot_unavailable=True, measured_at=moment + timedelta(days=10)))
    engine.dispose()


def manifest(target="0.6.0", **changes):
    return {"format_version": 1, "target_application_version": target, "supported_source_versions": ["0.5.1"],
            "target_alembic_revision": HEAD, "build_identity": "isolated-build", "updater_protocol": 1,
            "migration": "same-schema", **changes}


def write_package(path, value=None, *, extra=None, missing=None, build_override=None):
    value = value or manifest()
    build = {"application_version": value["target_application_version"], "alembic_revision": value["target_alembic_revision"],
             "build_identity": value["build_identity"]}
    build.update(build_override or {})
    files = {name: b"isolated fixture" for name in REQUIRED}
    files[CENTER] = files[SERVER] = value["target_application_version"].encode()
    files["app/build-info.json"] = json.dumps(build).encode()
    for source in MIGRATIONS.rglob("*.py"):
        files["app/migrations/" + source.relative_to(MIGRATIONS).as_posix()] = source.read_bytes()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", json.dumps(value))
        for name, contents in files.items():
            if name != missing:
                archive.writestr("payload/SeedLab/" + name, contents)
        for name, contents in (extra or {}).items():
            archive.writestr(name, contents)
    return path


@pytest.fixture
def deployment(tmp_path):
    root = tmp_path / "Managed Root"
    program = root / "App/v0.5.1/SeedLab"
    program.mkdir(parents=True)
    for name in (CENTER, SERVER):
        (program / name).write_text("0.5.1")
    shutil.copytree(MIGRATIONS, program / "app/migrations", ignore=shutil.ignore_patterns("__pycache__"))
    data = tmp_path / "External Data"
    database = data / "data/seedlab.db"
    database.parent.mkdir(parents=True)
    upgrade_database("sqlite:///" + database.as_posix(), MIGRATIONS)
    populate_business(database)
    ConfigStore(data / "config/seedlab.json").save(DeploymentSettings(auto_backup_enabled=False))
    deployment_identity(data)
    atomic_json(program / "config/installation.json", {"schema_version": 1, "data_root": str(data)})
    store = DeploymentStore(root)
    slot = {"version": "0.5.1", "program_root": str(program), "build_identity": "frozen-v0.5.1", "revision": HEAD}
    store.create(slot, data)
    for name in (LAUNCHER, UPDATER):
        (root / name).write_text("isolated helper")
    yield store, data, program


class Runtime:
    def __init__(self, store, fail=None):
        self.store, self.fail = store, fail
        self.events = []
        self.source = store.load()["current"]["version"]
    def request_handoff(self, path, program): self.events.append("stop-source")
    def start(self, state):
        self.events.append("start-candidate")
        assert self.store.load()["current"]["version"] == self.source
    def healthy(self, state):
        self.events.append("health")
        assert self.store.load()["current"]["version"] == self.source
        if self.fail:
            raise OperationsError("候选程序检查失败")
    def stop(self, state): self.events.append("stop-candidate")
    def launch_current(self): self.events.append("launch-current")


def executor(store, fail=None):
    runtime = Runtime(store, fail)
    return UpgradeExecutor(store.root, runtime=runtime, program_guard=lambda program: nullcontext(),
                           version_reader=lambda file: file.read_text()), runtime


def business_rows(database):
    with closing(sqlite3.connect(database)) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {table: connection.execute('SELECT * FROM "' + table + '" ORDER BY rowid').fetchall()
                for table in tables if table not in {"users", "sessions"}}


def test_launcher_current_data_reference_and_previous(deployment):
    store, data, program = deployment
    command = launch_command(store.root, startup=True)
    assert command == [str(program / CENTER), "--data-root", str(data), "--startup"]
    assert store.load()["previous"] is None


def test_launcher_missing_current_does_not_guess_another_slot(deployment):
    store, _, program = deployment
    (program / CENTER).unlink()
    with pytest.raises(OperationsError, match="程序文件缺失"):
        launch_command(store.root)


def test_launcher_missing_database_never_initializes(deployment):
    store, data, _ = deployment
    (data / "data/seedlab.db").unlink()
    with pytest.raises(OperationsError, match="空数据"):
        launch_command(store.root)
    assert not (data / "data/seedlab.db").exists()


def test_pending_launcher_opens_updater_not_candidate(deployment, tmp_path):
    store, _, _ = deployment
    core, runtime = executor(store)
    core.stage(write_package(tmp_path / "upgrade.zip"))
    assert launch_command(store.root) == [str(store.root / UPDATER), "--root", str(store.root)]
    assert runtime.events == []


@pytest.mark.parametrize("changes", [{"format_version": 2}, {"updater_protocol": 2},
    {"supported_source_versions": ["0.4.1"]}, {"target_application_version": "0.5.0"},
    {"target_application_version": "broken"}, {"target_alembic_revision": ""}])
def test_package_manifest_and_version_rejections(tmp_path, changes):
    package = write_package(tmp_path / "upgrade.zip", manifest(**changes))
    with pytest.raises(OperationsError): inspect_package(package, "0.5.1")


@pytest.mark.parametrize("name", ["payload/SeedLab/../../escape", "/outside", "C:/outside", "payload/SeedLab/C:evil",
    "payload/SeedLab/../escape", "payload/SeedLab/app/BUILD-INFO.JSON", "payload/SeedLab/data/seedlab.db"])
def test_safe_extraction_rejects_unsafe_or_duplicate_destinations(tmp_path, name):
    package = write_package(tmp_path / "upgrade.zip", extra={name: b"bad"})
    destination = tmp_path / "stage"
    with pytest.raises(OperationsError): extract_package(package, destination, "0.5.1")
    assert not destination.exists()


def test_package_crc_failure_is_detected_before_staging(tmp_path):
    package = write_package(tmp_path / "upgrade.zip")
    content = package.read_bytes()
    assert b"isolated fixture" in content
    package.write_bytes(content.replace(b"isolated fixture", b"damaged! fixture", 1))
    with pytest.raises(OperationsError): inspect_package(package, "0.5.1")


@pytest.mark.parametrize("missing", [CENTER, SERVER, "app/build-info.json", "app/web/index.html"])
def test_required_payload_files(tmp_path, missing):
    with pytest.raises(OperationsError): inspect_package(write_package(tmp_path / "upgrade.zip", missing=missing))


def test_manifest_and_payload_build_identity_must_agree(tmp_path):
    with pytest.raises(OperationsError):
        inspect_package(write_package(tmp_path / "upgrade.zip", build_override={"build_identity": "another-build"}))


def test_staging_failure_does_not_stop_source_or_publish_pending(deployment, tmp_path):
    store, _, _ = deployment
    core, runtime = executor(store)
    with pytest.raises(OperationsError): core.stage(write_package(tmp_path / "bad.zip", missing=SERVER))
    assert runtime.events == [] and store.load()["pending"] is None


def test_application_upgrade_backup_health_commit_and_data_unchanged(deployment, tmp_path):
    store, data, source = deployment
    before = business_rows(data / "data/seedlab.db")
    core, runtime = executor(store)
    staged = core.stage(write_package(tmp_path / "upgrade.zip"))
    assert staged["current"]["version"] == "0.5.1" and runtime.events == []
    result = core.activate()
    assert result["current"]["version"] == "0.6.0" and result["previous"]["program_root"] == str(source)
    assert result["pending"] is None and result["data_root"] == str(data)
    assert business_rows(data / "data/seedlab.db") == before
    assert len(list((data / "backups/before-upgrade").glob("*.db"))) == 1
    assert runtime.events == ["stop-source", "start-candidate", "health", "stop-candidate", "launch-current"]
    command = launch_command(store.root, start_server=True)
    assert "--deployment-root" in command and "--start-server" in command
    restored = core.rollback()
    assert restored["current"]["version"] == "0.5.1" and business_rows(data / "data/seedlab.db") == before


def test_failed_candidate_preserves_current_snapshot_and_interrupted_state(deployment, tmp_path):
    store, data, _ = deployment
    core, runtime = executor(store, fail=True)
    core.stage(write_package(tmp_path / "upgrade.zip"))
    with pytest.raises(OperationsError): core.activate()
    failed = store.load()
    assert failed["current"]["version"] == "0.5.1"
    assert failed["pending"]["phase"] == "failed" and Path(failed["pending"]["snapshot"]).is_file()
    assert launch_command(store.root)[0] == str(store.root / UPDATER)
    assert core.rollback()["pending"] is None
    assert (data / "data/seedlab.db").is_file()


def test_database_corruption_blocks_before_backup_or_candidate(deployment, tmp_path):
    store, data, _ = deployment
    core, runtime = executor(store)
    core.stage(write_package(tmp_path / "upgrade.zip"))
    (data / "data/seedlab.db").write_bytes(b"invalid sqlite")
    with pytest.raises(OperationsError): core.activate()
    assert "start-candidate" not in runtime.events
    assert store.load()["current"]["version"] == "0.5.1"
    assert not list((data / "backups").rglob("*.db"))


def test_cross_schema_target_is_blocked_before_source_stop(deployment, tmp_path):
    store, _, _ = deployment
    core, runtime = executor(store)
    with pytest.raises(OperationsError):
        core.stage(write_package(tmp_path / "upgrade.zip", manifest(target_alembic_revision="future")))
    assert runtime.events == [] and store.load()["pending"] is None


@pytest.mark.parametrize("standard", [True, False])
def test_bootstrap_reads_locator_adopts_standard_or_external_legacy_without_moving_data(tmp_path, standard):
    program = tmp_path / ("managed/App/v0.5.1/SeedLab" if standard else "Old SeedLab")
    program.mkdir(parents=True)
    for name in (CENTER, SERVER): (program / name).write_text("0.5.1")
    shutil.copytree(MIGRATIONS, program / "app/migrations", ignore=shutil.ignore_patterns("__pycache__"))
    data = tmp_path / "Original Data"
    (data / "data").mkdir(parents=True)
    database = data / "data/seedlab.db"
    upgrade_database("sqlite:///" + database.as_posix(), MIGRATIONS)
    ConfigStore(data / "config/seedlab.json").save(DeploymentSettings())
    atomic_json(program / "config/installation.json", {"schema_version": 1, "data_root": str(data)})
    reader = lambda file: file.read_text()
    slot, found, root = inspect_legacy(program / CENTER, version_reader=reader)
    tools = tmp_path / "tools"
    tools.mkdir()
    for name in (LAUNCHER, UPDATER): (tools / name).write_text("fixture")
    result = adopt(program / CENTER, root, tools, version_reader=reader)
    assert found == data and result["data_root"] == str(data)
    assert result["current"]["program_root"] == str(program)
    assert (root / LAUNCHER).is_file() and (root / UPDATER).is_file()
    assert (root / "App/v0.5.1/SeedLab").exists() == standard
    assert database.is_file()


@pytest.fixture
def accounts(deployment):
    _, data, _ = deployment
    database = data / "data/seedlab.db"
    engine = make_engine("sqlite:///" + database.as_posix())
    with Session(engine) as session:
        users = [User(username=name, display_name=name, password_hash=hash_password("old-password-123"),
                      is_admin=admin, must_change_password=True) for name, admin in (("admin", True), ("second", True), ("worker", False))]
        session.add_all(users)
        session.commit()
        ids = [user.id for user in users]
        for user in users: create_session(session, user)
    engine.dispose()
    return database, ids


def test_admin_recovery_only_changes_selected_credentials_and_sessions(accounts):
    database, ids = accounts
    before = business_rows(database)
    with closing(sqlite3.connect(database)) as connection:
        old_users = connection.execute("SELECT * FROM users ORDER BY id").fetchall()
        other_sessions = connection.execute("SELECT * FROM sessions WHERE user_id != ? ORDER BY id", (ids[0],)).fetchall()
    assert {user["id"] for user in administrators(database)} == set(ids[:2])
    reset_administrator(database, MIGRATIONS, ids[0], "recovered-password-123", "recovered-password-123")
    with closing(sqlite3.connect(database)) as connection:
        hashed, must_change = connection.execute("SELECT password_hash, must_change_password FROM users WHERE id=?", (ids[0],)).fetchone()
        assert check_password(hashed, "recovered-password-123") and not must_change
        assert connection.execute("SELECT count(*) FROM sessions WHERE user_id=?", (ids[0],)).fetchone()[0] == 0
        assert connection.execute("SELECT * FROM sessions WHERE user_id != ? ORDER BY id", (ids[0],)).fetchall() == other_sessions
        new_users = connection.execute("SELECT * FROM users ORDER BY id").fetchall()
        assert sum(left != right for left, right in zip(old_users, new_users)) == 1
    assert business_rows(database) == before


@pytest.mark.parametrize("case", ["non-admin", "missing", "weak", "confirmation"])
def test_admin_recovery_rejections_preserve_all_rows(accounts, case):
    database, ids = accounts
    with closing(sqlite3.connect(database)) as connection:
        before = list(connection.iterdump())
    identity = ids[2] if case == "non-admin" else "missing" if case == "missing" else ids[0]
    password = "short" if case == "weak" else "new-password-123"
    with pytest.raises(ValueError):
        reset_administrator(database, MIGRATIONS, identity, password, "different" if case == "confirmation" else password)
    with closing(sqlite3.connect(database)) as connection:
        assert list(connection.iterdump()) == before


def test_schema_display_uses_actual_revision_and_graph(deployment):
    _, data, _ = deployment
    assert schema_information(data / "data/seedlab.db", MIGRATIONS) == {"current": HEAD, "target": HEAD}


def test_managed_login_startup_points_to_stable_launcher(deployment):
    from control_center.paths import RuntimePaths
    from control_center.startup import StartupManager
    from test_portable_package import Registry
    store, data, program = deployment
    paths = RuntimePaths(program, layout="portable", data_root=data, deployment_root=store.root)
    manager = StartupManager(paths, Registry())
    manager.save(True)
    assert manager.command == f'"{store.root / LAUNCHER}" --startup'


def test_candidate_rejects_business_requests_but_keeps_health(deployment):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.core.config import Settings
    _, data, _ = deployment
    settings = Settings(_env_file=None, seedlab_database_url="sqlite:///" + (data / "data/seedlab.db").as_posix(),
                        seedlab_bootstrap_token_path=str(data / "data/bootstrap.token"),
                        seedlab_runtime_info={"candidate_id": "a" * 32, "probe_token": "local-test-token"})
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/experiments").status_code == 503
        assert client.post("/api/auth/login", json={"username": "admin", "password": "x"}).status_code == 503


@pytest.mark.parametrize("directory", ["App", "Updates", "Logs", "state"])
def test_data_cannot_overlap_managed_program_or_work_directories(deployment, directory):
    store, _, _ = deployment
    state = store.load()
    state["data_root"] = str(store.root / directory / "Existing Data")
    with pytest.raises(OperationsError):
        store.save(state)


def test_backup_failure_never_starts_candidate_or_commits(deployment, tmp_path, monkeypatch):
    from production_ops import database
    store, data, _ = deployment
    before = business_rows(data / "data/seedlab.db")
    core, runtime = executor(store)
    core.stage(write_package(tmp_path / "upgrade.zip"))
    def fail(*args, **kwargs):
        raise OSError("disk unavailable")
    monkeypatch.setattr(database.BackupService, "snapshot", fail)
    with pytest.raises(OperationsError):
        core.activate()
    assert "start-candidate" not in runtime.events
    assert store.load()["pending"]["snapshot"] is None
    assert store.load()["current"]["version"] == "0.5.1"
    assert business_rows(data / "data/seedlab.db") == before


def test_second_upgrade_keeps_one_previous_and_only_removes_owned_obsolete_app(deployment, tmp_path):
    store, data, old = deployment
    (old.parent / ".seedlab-managed-slot").write_text("owned")
    core, _ = executor(store)
    core.stage(write_package(tmp_path / "first.zip"))
    core.activate()
    assert old.is_dir()
    next_core, _ = executor(store)
    next_core.stage(write_package(tmp_path / "next.zip", manifest("0.6.1", supported_source_versions=["0.6.0"])))
    result = next_core.activate()
    assert result["current"]["version"] == "0.6.1" and result["previous"]["version"] == "0.6.0"
    assert not old.parent.exists()
    assert (data / "data/seedlab.db").is_file()
    assert len(list((data / "backups/before-upgrade").glob("*.db"))) == 2


def test_partial_bootstrap_tool_install_can_resume(deployment, tmp_path):
    store, data, old = deployment
    (store.root / UPDATER).unlink()
    resources = tmp_path / "resources"
    resources.mkdir()
    for name in (LAUNCHER, UPDATER):
        (resources / name).write_text("new helper")
    before = business_rows(data / "data/seedlab.db")
    adopt(old / CENTER, store.root, resources, version_reader=lambda file: file.read_text())
    assert (store.root / UPDATER).read_text() == "new helper"
    assert (store.root / LAUNCHER).read_text() == "isolated helper"
    assert business_rows(data / "data/seedlab.db") == before


def test_windows_executable_guard_releases_its_handles(deployment):
    import os
    if os.name != "nt":
        pytest.skip("Windows executable sharing contract")
    from production_ops.windows import closed_program
    _, _, program = deployment
    with closed_program(program):
        with pytest.raises(PermissionError):
            (program / SERVER).write_text("must be blocked")
    assert (program / SERVER).read_text() == "0.5.1"


def pump_until(app, condition):
    import time
    deadline = time.monotonic() + 10
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert condition()


def test_bootstrap_gui_picker_when_discovery_has_no_match(deployment, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from production_ops import gui
    store, _, program = deployment
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui, "discover", lambda: [])
    monkeypatch.setattr(gui.QFileDialog, "getOpenFileName", lambda *args: (str(program / CENTER), ""))
    monkeypatch.setattr(gui, "inspect_legacy", lambda path: inspect_legacy(path, version_reader=lambda file: file.read_text()))
    window = gui.UpgradeWindow(bootstrap=True, isolated=True)
    try:
        assert not window.legacy.text()
        window.choose_legacy()
        pump_until(app, lambda: not window.busy)
        assert window.root.text() == str(store.root)
        assert "数据库检查正常" in window.details.text()
    finally:
        window.close()


def test_admin_gui_normally_stops_and_restarts_without_logging_password(accounts, deployment, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from control_center.paths import RuntimePaths
    from control_center.server_manager import ServerProcessManager, State
    from control_center.widgets.production_panels import AdminRecoveryPanel
    database, ids = accounts
    store, data, _ = deployment
    app = QApplication.instance() or QApplication([])
    manager = ServerProcessManager(RuntimePaths(ROOT, data_root=data), polling=False)
    manager.process, manager.state = object(), State.RUNNING
    events = []
    def stop():
        events.append("stop")
        manager.process, manager.state = None, State.STOPPED
        assert not manager.can_start
    monkeypatch.setattr(manager, "stop", stop)
    monkeypatch.setattr(manager, "start", lambda: events.append("restart"))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    panel = AdminRecoveryPanel(manager)
    panel.loaded((schema_information(database, MIGRATIONS), administrators(database)))
    panel.admin.setCurrentIndex(panel.admin.findData(ids[0]))
    secret = "do-not-log-this-password-123"
    panel.password.setText(secret)
    panel.confirm.setText(secret)
    try:
        panel.request_reset()
        pump_until(app, lambda: not panel.busy)
        assert events == ["stop", "restart"] and not manager.maintenance
        assert not panel.password.text() and not panel.confirm.text()
        assert "已重置" in panel.message.text()
        for file in data.rglob("*.log"):
            assert secret not in file.read_text(encoding="utf-8")
    finally:
        manager.stop_checks()
        panel.close()
