"""Production runtime setup never touches repository data, config or backups."""
from dataclasses import replace
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.services.migrations import upgrade_database, migration_heads, check_database_schema
from app.services.sqlite_backup import check_database
from control_center.config_store import DeploymentSettings, ConfigStore
from control_center.paths import RuntimePaths
from control_center.installation import (InstallationStore, InstallationError, initialize_data_root,
    inspect_data_root, validate_location)


@pytest.fixture
def runtime(tmp_path):
    program = tmp_path / "program"
    migrations = program / "backend/alembic"
    shutil.copytree(ROOT / "backend/alembic", migrations, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    web = program / "frontend/dist"
    web.mkdir(parents=True)
    (web / "index.html").write_text("SeedLab isolated UI", encoding="utf-8")
    (program / "scripts").mkdir()
    (program / "scripts/run_prod.py").write_text("# Mock development launcher")
    return RuntimePaths(program_root=program, data_root=tmp_path / "SeedLabData")


def locator(runtime):
    return InstallationStore(runtime, allow_temporary=True)


def test_migration_api_empty_idempotent_explicit_paths_and_schema_check(runtime, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runtime.database.parent.mkdir(parents=True)
    url = "sqlite:///" + runtime.database.as_posix()
    assert upgrade_database(url, runtime.migration_root) == ("c6d91f28a405",)
    before = runtime.database.read_bytes()
    assert upgrade_database(url, runtime.migration_root) == migration_heads(runtime.migration_root)
    check_database_schema(url, runtime.migration_root)
    assert runtime.database.read_bytes() == before
    assert check_database(runtime.database).valid


def test_installation_missing_and_new_data_paths_with_last_commit(runtime, monkeypatch):
    store = locator(runtime)
    assert store.load() is None and not store.path.exists()
    original_save = store.save
    def finish(data_root):
        assert runtime.config_file.is_file()
        assert check_database(runtime.database).valid
        with closing(sqlite3.connect(runtime.database)) as db:
            assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("c6d91f28a405",)
        assert not store.path.exists()
        original_save(data_root)
    monkeypatch.setattr(store, "save", finish)
    initialize_data_root(runtime, DeploymentSettings(auto_backup_retention=9), store)
    assert store.load() == runtime.data_root
    assert json.loads(store.path.read_text()) == {"schema_version":1, "data_root":str(runtime.data_root)}
    assert ConfigStore(runtime.config_file).load().auto_backup_retention == 9
    for path in (runtime.database, runtime.bootstrap_token, runtime.config_file, runtime.logs, runtime.backups):
        assert path.is_relative_to(runtime.data_root)
    for directory in ("data", "config", "logs", "backups/auto", "backups/manual", "backups/before-upgrade"):
        assert (runtime.data_root / directory).is_dir()
    assert not (runtime.program_root / "backend/data").exists()


@pytest.mark.parametrize("payload", ["broken", '{"schema_version":2,"data_root":"D:/data"}',
    '{"schema_version":1,"data_root":"relative"}', '{"schema_version":1,"data_root":""}',
    '{"schema_version":1,"data_root":null}', '{"schema_version":1,"extra":true}'])
def test_invalid_installation_preserved(runtime, payload):
    store = locator(runtime)
    store.path.parent.mkdir(parents=True)
    store.path.write_text(payload)
    assert store.load() is None and store.warning
    assert store.path.read_text() == payload


def test_installation_atomic_failure_preserves_old_locator(runtime, tmp_path, monkeypatch):
    import control_center.installation as module
    store = locator(runtime)
    runtime.data_root.mkdir()
    store.save(runtime.data_root)
    old = store.path.read_bytes()
    other = tmp_path / "other-data"
    other.mkdir()
    monkeypatch.setattr(module.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("denied")))
    with pytest.raises(OSError): store.save(other)
    assert store.path.read_bytes() == old
    assert not list(store.path.parent.glob("*.tmp"))


def test_installation_does_not_silently_recreate_missing_database(runtime):
    store = locator(runtime)
    initialize_data_root(runtime, DeploymentSettings(), store)
    marker = store.path.read_bytes()
    runtime.database.unlink()
    assert store.load() is None and store.warning
    assert store.path.read_bytes() == marker and not runtime.database.exists()


def test_data_root_rejects_files_resources_temp_and_unknown_content(runtime, tmp_path):
    file = tmp_path / "file"
    file.write_text("user file")
    for location in (file, runtime.program_root, runtime.web_root, runtime.migration_root, tmp_path):
        with pytest.raises(InstallationError):
            validate_location(location, runtime, allow_temporary=True)
    with pytest.raises(InstallationError, match="临时目录"):
        validate_location(runtime.data_root, runtime)
    runtime.data_root.mkdir()
    unknown = runtime.data_root / "notes.txt"
    unknown.write_text("user notes")
    with pytest.raises(InstallationError, match="不会被覆盖"):
        inspect_data_root(runtime, allow_temporary=True)
    assert unknown.read_text() == "user notes"


def test_unwritable_or_failed_migration_never_commits_installation(runtime, monkeypatch):
    import control_center.installation as module
    store = locator(runtime)
    original_probe = module.probe_writable
    monkeypatch.setattr(module, "probe_writable", lambda path: (_ for _ in ()).throw(InstallationError("所选目录无法写入")))
    with pytest.raises(InstallationError): initialize_data_root(runtime, DeploymentSettings(), store)
    assert not store.path.exists() and not runtime.data_root.exists()
    monkeypatch.setattr(module, "probe_writable", original_probe)
    monkeypatch.setattr(module, "upgrade_database", lambda *args: (_ for _ in ()).throw(RuntimeError("migration failed")))
    with pytest.raises(RuntimeError): initialize_data_root(runtime, DeploymentSettings(), store)
    assert not store.path.exists() and runtime.config_file.exists()


def test_existing_valid_data_requires_consent_and_preserves_config_users(runtime):
    store = locator(runtime)
    settings = DeploymentSettings(access_mode="remote", remote_url="https://example.org", auto_backup_retention=8)
    initialize_data_root(runtime, settings, store)
    from app.core.auth import hash_password
    with closing(sqlite3.connect(runtime.database)) as db:
        db.execute("INSERT INTO users(id,username,display_name,password_hash,is_admin,is_active,must_change_password,created_at) VALUES(?,?,?,?,?,?,?,?)",
            ("existing-user", "existing", "已有管理员", hash_password("existing-password"), 1, 1, 0, "2026-10-01"))
        db.commit()
    inspection = inspect_data_root(runtime, allow_temporary=True)
    assert inspection.existing and inspection.has_users and inspection.settings == settings
    before = runtime.config_file.read_bytes()
    with pytest.raises(InstallationError, match="明确选择"):
        initialize_data_root(runtime, DeploymentSettings(), store)
    initialize_data_root(runtime, DeploymentSettings(), store, reuse=True)
    assert runtime.config_file.read_bytes() == before
    assert inspect_data_root(runtime, allow_temporary=True).has_users


@pytest.mark.parametrize("failure", ["database", "config", "revision"])
def test_existing_bad_data_rejected_without_overwrite(runtime, failure):
    store = locator(runtime)
    initialize_data_root(runtime, DeploymentSettings(), store)
    if failure == "database": runtime.database.write_bytes(b"invalid sqlite")
    elif failure == "config": runtime.config_file.write_text("bad json")
    else:
        with closing(sqlite3.connect(runtime.database)) as db:
            db.execute("UPDATE alembic_version SET version_num='unknown'")
            db.commit()
    before = runtime.database.read_bytes(), runtime.config_file.read_bytes(), store.path.read_bytes()
    with pytest.raises(InstallationError): inspect_data_root(runtime, allow_temporary=True)
    assert before == (runtime.database.read_bytes(), runtime.config_file.read_bytes(), store.path.read_bytes())


def test_bootstrap_new_and_existing_user_data_root(runtime):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.bootstrap import ensure_bootstrap_token
    from app.core.config import Settings
    from app.models import User
    from app.core.auth import hash_password
    initialize_data_root(runtime, DeploymentSettings(), locator(runtime))
    settings = Settings(_env_file=None, seedlab_database_url="sqlite:///"+runtime.database.as_posix(),
                        seedlab_bootstrap_token_path=str(runtime.bootstrap_token))
    engine = create_engine(settings.seedlab_database_url)
    try:
        with Session(engine) as db:
            ensure_bootstrap_token(db, settings)
            assert runtime.bootstrap_token.is_file()
            db.add(User(username="existing", display_name="已有管理员", password_hash=hash_password("existing-password"), is_admin=True))
            db.commit()
            runtime.bootstrap_token.unlink()
            ensure_bootstrap_token(db, settings)
            assert not runtime.bootstrap_token.exists()
    finally: engine.dispose()


@pytest.mark.parametrize("layout", ["development", "portable"])
def test_server_command_from_roots_and_settings(runtime, layout):
    paths = RuntimePaths(program_root=runtime.program_root, data_root=runtime.data_root, layout=layout)
    settings = DeploymentSettings(access_mode="remote", remote_url="https://example.org", port=8851)
    stop = paths.new_stop_file()
    command = paths.server_command(stop, settings)
    if layout == "portable": assert command[0] == str(paths.server_executable) and ".venv" not in " ".join(command)
    else: assert command[:3] == [str(paths.python), "-u", str(paths.program_root / "scripts/run_prod.py")]
    for key, value in (("--database", paths.database), ("--web-root", paths.web_root),
        ("--migration-root", paths.migration_root), ("--bootstrap-token", paths.bootstrap_token),
        ("--cookie-secure", "true"), ("--host", "127.0.0.1"), ("--port", "8851"), ("--stop-file", stop)):
        assert command[command.index(key)+1] == str(value)
    assert stop.is_relative_to(paths.data_root)


@pytest.fixture
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def wait(app, predicate):
    deadline = time.monotonic()+10
    while not predicate() and time.monotonic()<deadline:
        app.processEvents(); time.sleep(.005)
    assert predicate()


@pytest.mark.parametrize("mode", ["lan", "remote"])
def test_external_confirms_only_localhost_despite_saved_mode(runtime, qt_app, mode):
    from control_center.server_manager import ServerProcessManager, State
    from control_center.main_window import MainWindow
    from app.version import VERSION
    ConfigStore(runtime.config_file).save(DeploymentSettings(access_mode=mode, lan_address="192.168.1.4", remote_url="https://example.org", port=8851))
    manager = ServerProcessManager(runtime, polling=False)
    manager.accept_health({"status":"ok", "version":VERSION})
    assert manager.state == State.EXTERNAL and manager.user_url == "http://127.0.0.1:8851"
    manager.apply_settings(replace(manager.config, port=8852))
    assert manager.health_url == manager.user_url == "http://127.0.0.1:8851"
    window = MainWindow(manager)
    assert "无法判断" in window.network_panel.current.text()
    assert window.access_card.value.text() == "外部服务"
    assert "未知" in window.management_grid.values["host"].text()
    window.ui_timer.stop();window.tray.hide();window.deleteLater();manager.stop_checks()


def test_wizard_five_steps_navigation_modes_summary_initialize(qt_app, runtime, monkeypatch):
    from PySide6.QtWidgets import QAbstractSpinBox
    from control_center.first_run import FirstRunWizard
    from control_center.network_service import LanAddress
    import control_center.widgets.operations_panels as panels
    monkeypatch.setattr(panels, "lan_addresses", lambda: [LanAddress("Ethernet", "192.168.1.4")])
    wizard = FirstRunWizard(runtime, locator(runtime))
    assert wizard.pages.count() == 5
    wizard.next(); assert wizard.pages.currentIndex() == 1
    wizard.root_edit.setText(str(runtime.data_root));wizard.next()
    wait(qt_app, lambda:not wizard.busy)
    assert wizard.pages.currentIndex() == 2
    wizard.back();assert wizard.pages.currentIndex() == 1
    wizard.next();wait(qt_app,lambda:not wizard.busy)
    assert wizard.network_panel.mode == "local"
    wizard.network_panel.modes["lan"].setChecked(True)
    assert wizard.settings().lan_address == "192.168.1.4"
    wizard.network_panel.modes["remote"].setChecked(True)
    wizard.next();assert wizard.pages.currentIndex() == 2 and wizard.error_label.text()
    wizard.network_panel.remote_edit.setText("https://example.org");wizard.next()
    assert wizard.pages.currentIndex() == 3
    assert wizard.settings_panel.retention.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
    wizard.settings_panel.retention.setValue(9);wizard.next()
    assert "9 份" in wizard.summary.text() and str(runtime.database) in wizard.summary.text()
    results=[];wizard.completed.connect(results.append);wizard.next()
    wait(qt_app,lambda:not wizard.busy)
    assert results == [runtime] and locator(runtime).load() == runtime.data_root
    wizard.deleteLater()


def test_wizard_existing_root_and_failure(qt_app, runtime, monkeypatch):
    from control_center.first_run import FirstRunWizard
    import control_center.first_run as module
    initialize_data_root(runtime, DeploymentSettings(auto_backup_retention=7), locator(runtime))
    wizard=FirstRunWizard(runtime, locator(runtime));wizard.next();wizard.root_edit.setText(str(runtime.data_root));wizard.next()
    wait(qt_app,lambda:not wizard.busy)
    assert wizard.pages.currentIndex()==1 and wizard.inspection.existing
    wizard.use_existing();assert wizard.pages.currentIndex()==2 and wizard.reuse
    assert wizard.settings_panel.retention.value()==7
    wizard.next();wizard.next()
    old=locator(runtime).path.read_bytes()
    monkeypatch.setattr(module,"initialize_data_root",lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError("failure")))
    wizard.next();wait(qt_app,lambda:not wizard.busy)
    assert wizard.error_label.text() and not wizard._completed
    assert locator(runtime).path.read_bytes()==old
    wizard.deleteLater()


def test_first_run_controller_success_then_reopen_uses_same_root(qt_app, runtime, monkeypatch):
    import control_center.app as module
    from control_center.server_manager import ServerProcessManager
    starts=[]
    def manager(paths):
        result=ServerProcessManager(paths,polling=False)
        monkeypatch.setattr(result,"start",lambda:starts.append(paths.data_root))
        return result
    monkeypatch.setattr(module,"ServerProcessManager",manager)
    controller=module.ApplicationController(runtime,locator(runtime))
    assert controller.wizard is not None and controller.window is None
    wizard=controller.wizard
    wizard.next();wizard.root_edit.setText(str(runtime.data_root));wizard.next();wait(qt_app,lambda:not wizard.busy)
    wizard.next();wizard.next();wizard.next();wait(qt_app,lambda:controller.window is not None)
    qt_app.processEvents()
    assert starts==[runtime.data_root]
    reopened=module.ApplicationController(runtime,locator(runtime))
    assert reopened.wizard is None and reopened.window.manager.paths.database==runtime.database
    for owner in (controller,reopened):
        owner.window.ui_timer.stop();owner.window.tray.hide();owner.window.hide();owner.window.manager.stop_checks();owner.window.deleteLater()
