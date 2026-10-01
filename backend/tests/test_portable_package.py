"""Packaging boundaries, user-session IPC and startup settings, all isolated."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from control_center.paths import RuntimePaths
from control_center.config_store import DeploymentSettings, ConfigStore, ConfigError
from control_center.startup import StartupManager
from control_center.single_instance import SingleInstance
from control_center.installation import InstallationStore, initialize_data_root, InstallationError


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    import control_center.installation as installation
    monkeypatch.setattr(installation, "ensure_port_available", lambda settings: None)
    program = tmp_path / "种子试验 Program"
    web = program / "frontend/dist"
    web.mkdir(parents=True)
    (web / "index.html").write_text("isolated")
    shutil.copytree(ROOT / "backend/alembic", program / "backend/alembic",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (program / "scripts").mkdir()
    (program / "scripts/run_prod.py").write_text("# isolated launcher")
    return RuntimePaths(program, data_root=tmp_path / "SeedLabData")


class Registry:
    def __init__(self):
        self.value = None
        self.writes = []
    def read(self): return self.value
    def write(self, value): self.value = value; self.writes.append(value)
    def delete(self): self.value = None; self.writes.append(None)


def test_frozen_roots_and_visible_resources_are_independent(tmp_path, monkeypatch):
    program = tmp_path / "中文 Portable"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(program / "_internal"), raising=False)
    monkeypatch.setattr(sys, "executable", str(program / "SeedLab Control Center.exe"))
    paths = RuntimePaths.discover(data_root=tmp_path / "data-root")
    assert paths.program_root == program and paths.resource_root == program / "_internal"
    assert paths.web_root == program / "app/web" and paths.migration_root == program / "app/migrations"
    command = paths.server_command(paths.new_stop_file(), DeploymentSettings())
    assert command[0] == str(program / "SeedLabServer.exe")
    assert not any(value.endswith(".py") or ".venv" in value for value in command)


def test_missing_portable_server_has_user_message(runtime, qt_app, monkeypatch):
    from control_center.server_manager import ServerProcessManager, State
    paths = replace(runtime, layout="portable")
    manager = ServerProcessManager(paths, polling=False)
    monkeypatch.setattr(manager, "_port_free", lambda:True)
    manager.start()
    assert manager.state == State.ERROR and "运行文件缺失" in manager.message
    assert manager.process is None
    manager.stop_checks()


def test_old_config_defaults_false_and_roundtrip(runtime):
    runtime.config_file.parent.mkdir(parents=True)
    runtime.config_file.write_text(json.dumps({"schema_version":1,"auto_backup_retention":14}))
    store=ConfigStore(runtime.config_file)
    assert store.load().auto_start_server is False
    store.save(replace(store.settings,auto_start_server=True))
    assert ConfigStore(runtime.config_file).load().auto_start_server is True
    with pytest.raises(ConfigError): DeploymentSettings(auto_start_server=1)


def test_registry_quote_stale_update_disable_and_development_guard(runtime):
    registry=Registry()
    portable=replace(runtime,layout="portable")
    portable.control_executable.write_bytes(b"mock exe")
    manager=StartupManager(portable,registry)
    assert manager.command == f'"{portable.control_executable}" --startup'
    assert not manager.state().enabled
    registry.value='"D:\\old place\\SeedLab Control Center.exe" --startup'
    assert manager.state().stale and "旧程序位置" in manager.state().warning
    assert registry.writes == []
    manager.save(True)
    assert registry.value==manager.command and manager.state().enabled
    manager.save(False)
    assert registry.value is None
    development=StartupManager(runtime,registry)
    before=registry.writes.copy()
    assert not development.available
    with pytest.raises(ValueError): development.save(True)
    assert registry.writes==before


def test_single_instance_notifies_owner_and_reacquires_after_close(qt_app):
    name="seedlab-test-"+uuid4().hex
    first=SingleInstance(name);second=SingleInstance(name)
    received=[];first.activated.connect(lambda:received.append(True))
    try:
        assert first.acquire() is True
        assert second.acquire() is False
        deadline=time.monotonic()+3
        while not received and time.monotonic()<deadline:
            qt_app.processEvents();time.sleep(.005)
        assert received==[True]
        first.close()
        assert second.acquire() is True
    finally: first.close();second.close()


@pytest.mark.parametrize("startup,auto,external",[(False,False,False),(False,True,False),(True,False,False),(True,True,False),(False,True,True)])
def test_startup_visibility_autostart_and_external_guard(runtime,qt_app,monkeypatch,startup,auto,external):
    import control_center.app as module
    from control_center.server_manager import ServerProcessManager
    from app.version import VERSION
    store=InstallationStore(runtime,allow_temporary=True)
    initialize_data_root(runtime,DeploymentSettings(auto_start_server=auto),store)
    starts=[]
    def factory(paths):
        manager=ServerProcessManager(paths,polling=False)
        if external:manager.accept_health({"status":"ok","version":VERSION})
        monkeypatch.setattr(manager,"start",lambda:starts.append(True))
        return manager
    monkeypatch.setattr(module,"ServerProcessManager",factory)
    monkeypatch.setattr(QSystemTrayIcon,"isSystemTrayAvailable",lambda:True)
    controller=module.ApplicationController(runtime,store,startup=startup)
    qt_app.processEvents()
    assert starts == ([True] if auto and not external else [])
    assert controller.window.isVisible() is not startup
    controller.activate();assert controller.window.isVisible()
    window=controller.window
    window.ui_timer.stop();window.manager.stop_checks();window.tray.hide();window.hide();window.deleteLater()


def test_startup_without_installation_always_shows_wizard(runtime,qt_app):
    from control_center.app import ApplicationController, parse_args
    assert parse_args(["--startup"]).startup
    controller=ApplicationController(runtime,InstallationStore(runtime,allow_temporary=True),startup=True)
    assert controller.window is None and controller.wizard.isVisible()
    controller.wizard.hide();controller.wizard.deleteLater()


def test_program_root_write_failure_precedes_data_changes(runtime,monkeypatch):
    import control_center.installation as module
    store=InstallationStore(runtime,allow_temporary=True)
    original=module.probe_writable
    def probe(path):
        if path==store.path.parent:raise InstallationError("denied")
        original(path)
    monkeypatch.setattr(module,"probe_writable",probe)
    with pytest.raises(InstallationError,match="当前程序目录不可写"):
        initialize_data_root(runtime,DeploymentSettings(),store)
    assert not runtime.data_root.exists() and not store.path.exists()


def test_candidate_scan_rejects_data_and_developer_assets():
    spec=importlib.util.spec_from_file_location("candidate_gate",ROOT/"scripts/check_portable.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for name in ("data/seedlab.db","app/seedlab.db-wal","bootstrap.token","config/installation.json","config/instance.json",
                 ".env","backups/snapshot","_internal/tests/test.py","frontend/src/a.ts",".venv/python.exe"):
        assert module.forbidden(name)
    assert not module.forbidden("_internal/tzdata/zoneinfo/Asia/Shanghai")
    assert not module.forbidden("app/migrations/versions/3179cf93a5f4_initial.py")
