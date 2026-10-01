"""Deployment ownership, first-run isolation, applied modes and product identity."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import struct
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from PySide6.QtNetwork import QNetworkReply
from app.core.config import Settings, get_settings
from app.main import create_app
from app.services.runtime_identity import deployment_identity, IdentityError
from app.version import VERSION
from control_center.paths import RuntimePaths
from control_center.config_store import DeploymentSettings
from control_center.installation import initialize_data_root, InstallationStore, InstallationError
from control_center.server_manager import ServerProcessManager, State


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def runtime(tmp_path):
    program = tmp_path / "程序 Program"
    web = program / "frontend/dist"
    web.mkdir(parents=True)
    (web / "index.html").write_text("isolated SeedLab")
    return RuntimePaths(program, data_root=tmp_path / "全新数据",
                        migration_root=ROOT / "backend/alembic")


@pytest.fixture
def manager(runtime, qt_app):
    result = ServerProcessManager(runtime, polling=False)
    yield result
    result.stop_checks()
    for logger in (result.control_log, result.server_log):
        for handler in list(logger.handlers):
            handler.close(); logger.removeHandler(handler)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_identity_stable_distinct_and_cloned_root_cannot_match(tmp_path):
    first = deployment_identity(tmp_path / "一")
    assert deployment_identity(first.data_root) == first
    second = deployment_identity(tmp_path / "二")
    assert second.instance_id != first.instance_id and second.probe_token != first.probe_token
    clone = tmp_path / "复制"
    shutil.copytree(first.data_root, clone)
    copied = deployment_identity(clone)
    assert copied.instance_id == first.instance_id
    assert not copied.matches({"instance_id": first.instance_id, "data_root": str(first.data_root)})
    assert copied.matches({"instance_id": copied.instance_id, "data_root": str(clone)})


def test_instance_lock_separates_deployments_and_unifies_same_data(runtime, qt_app):
    from control_center.single_instance import instance_name, SingleInstance
    other = replace(runtime, program_root=runtime.program_root.parent / "另一份程序",
                    data_root=runtime.data_root.parent / "另一份数据")
    same_data = replace(other, data_root=runtime.data_root)
    assert instance_name(runtime) != instance_name(other)
    assert instance_name(runtime, scope="data") == instance_name(same_data, scope="data")
    first = SingleInstance(instance_name(runtime, scope="data"))
    another = SingleInstance(instance_name(other, scope="data"))
    duplicate = SingleInstance(instance_name(same_data, scope="data"))
    activated = []; first.activated.connect(lambda: activated.append(True))
    try:
        assert first.acquire() and another.acquire()
        assert not duplicate.acquire() and activated == [True]
    finally:
        first.close(); another.close(); duplicate.close()


def test_invalid_identity_is_preserved(tmp_path):
    identity = deployment_identity(tmp_path)
    path = tmp_path / "config/instance.json"
    path.write_text('{"instance_id":"bad"}')
    before = path.read_bytes()
    with pytest.raises(IdentityError): deployment_identity(tmp_path)
    assert path.read_bytes() == before
    assert identity.instance_id


def test_occupied_port_blocks_before_data_or_locator_writes(runtime):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); sock.listen()
        store = InstallationStore(runtime, allow_temporary=True)
        with pytest.raises(InstallationError, match="修改端口"):
            initialize_data_root(runtime, DeploymentSettings(port=sock.getsockname()[1]), store)
        assert not runtime.data_root.exists() and not store.path.exists()


def test_wizard_port_conflict_stays_on_access_step(runtime, qt_app):
    from control_center.first_run import FirstRunWizard
    wizard = FirstRunWizard(runtime, InstallationStore(runtime, allow_temporary=True))
    try:
        wizard.paths = runtime
        wizard.pages.setCurrentIndex(2)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); sock.listen()
            wizard.network_panel.port_edit.setValue(sock.getsockname()[1])
            wizard.next()
            assert wizard.pages.currentIndex() == 2 and "修改端口" in wizard.error_label.text()
        wizard.network_panel.port_edit.setValue(free_port())
        wizard.next()
        assert wizard.pages.currentIndex() == 3
    finally:
        wizard.network_panel.checker.stop(); wizard.hide(); wizard.deleteLater()


def test_two_fresh_roots_setup_and_reopen_keep_accounts_separate(runtime, monkeypatch):
    roots = [runtime, replace(runtime, data_root=runtime.data_root.parent / "另一块盘的数据")]
    tokens = []
    for i, paths in enumerate(roots):
        store = InstallationStore(paths, allow_temporary=True)
        settings = DeploymentSettings(port=free_port())
        initialize_data_root(paths, settings, store)
        assert store.load() == paths.data_root
        with sqlite3.connect(paths.database) as db:
            assert db.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        token = paths.bootstrap_token.read_text().strip(); tokens.append(token)
        with TestClient(create_app(Settings(_env_file=None,
                seedlab_database_url="sqlite:///" + paths.database.as_posix(),
                seedlab_bootstrap_token_path=str(paths.bootstrap_token)))) as client:
            assert client.get("/api/setup/status").json() == {"initialized": False}
            response = client.post("/api/setup/bootstrap", json={"bootstrap_token": token,
                "username": f"isolated-{i}", "display_name": "隔离管理员",
                "password": "isolated-pass-123", "confirm_password": "isolated-pass-123"})
            assert response.status_code == 201, response.text
            assert client.get("/api/setup/status").json() == {"initialized": True}
        assert not paths.bootstrap_token.exists()
        identity = deployment_identity(paths.data_root)
        initialize_data_root(paths, settings, store, reuse=True)
        assert deployment_identity(paths.data_root) == identity and not paths.bootstrap_token.exists()
        with sqlite3.connect(paths.database) as db:
            assert db.execute("SELECT username FROM users").fetchall() == [(f"isolated-{i}",)]
    assert tokens[0] != tokens[1]
    get_settings.cache_clear()


def test_runtime_metadata_requires_deployment_probe_and_never_returns_secret(runtime):
    initialize_data_root(runtime, DeploymentSettings(port=free_port()), InstallationStore(runtime, allow_temporary=True))
    identity = deployment_identity(runtime.data_root)
    info = {"instance_id": identity.instance_id, "data_root": str(identity.data_root),
            "probe_token": identity.probe_token, "port": 8855, "access_mode": "lan", "bind_host": "0.0.0.0", "pid": 42}
    settings = Settings(_env_file=None, seedlab_database_url="sqlite:///" + runtime.database.as_posix(),
                        seedlab_bootstrap_token_path=str(runtime.bootstrap_token), seedlab_runtime_info=info)
    with TestClient(create_app(settings)) as client:
        for headers in ({}, {"X-SeedLab-Control": "wrong-deployment"}):
            assert client.get("/api/health", headers=headers).json() == {"status": "ok", "version": VERSION}
        response = client.get("/api/health", headers={"X-SeedLab-Control": identity.probe_token})
        assert response.json()["access_mode"] == "lan" and response.json()["instance_id"] == identity.instance_id
        assert response.json()["data_root"] == str(runtime.data_root)
        assert identity.probe_token not in response.text and "probe_token" not in response.json()


def test_foreign_and_legacy_services_never_read_setup_or_gain_control(manager, runtime_health):
    for payload in ({"status": "ok", "version": VERSION}, runtime_health(manager, instance_id="other"),
                    runtime_health(manager, data_root=str(manager.paths.data_root.parent / "旧数据"))):
        manager.initialized = True
        manager.accept_health(payload)
        assert manager.state == State.OTHER and manager.initialized is None
        assert not manager.can_open and not manager.can_start and not manager.can_stop
        assert manager._setup_reply is None
        manager.stop(); manager.restart(); manager.force_stop()
        assert manager.state == State.OTHER and manager.process is None


@pytest.mark.parametrize("changes", [{"instance_id": "other"}, {"data_root": "D:/other-data"},
    {"pid": 999}, {"port": 9999}, {"access_mode": "lan", "bind_host": "0.0.0.0"}])
def test_owned_start_requires_identity_pid_port_and_actual_mode(manager, runtime_health, changes):
    manager.process = type("Child", (), {"pid": 77, "poll": lambda self: None})()
    manager.state = State.STARTING
    manager.running_config = DeploymentSettings()
    manager.accept_health(runtime_health(manager, **changes))
    assert manager.state == State.ERROR and not manager.health_ok
    assert "不一致" in manager.message


def test_saved_mode_stays_distinct_until_real_restart_is_confirmed(manager, runtime_health, monkeypatch):
    from control_center.main_window import MainWindow
    manager.process = type("Child", (), {"pid": 77, "poll": lambda self: None})()
    manager.running_config = DeploymentSettings()
    manager.state = State.STARTING
    manager.accept_health(runtime_health(manager))
    lan = replace(manager.config, access_mode="lan", lan_address="192.168.1.5")
    restarted = []; monkeypatch.setattr(manager, "restart", lambda: restarted.append(True))
    manager.apply_settings(lan, restart=True)
    assert restarted == [True] and manager.active_config.access_mode == "local"
    window = MainWindow(manager)
    try:
        assert "已保存配置不同" in window.management_message.text()
        assert window.access_card.value.text() == "仅本机使用"
        assert "已保存配置不同" in window.network_panel.current.text()
        manager.running_config = lan; manager.state = State.STARTING
        manager.accept_health(runtime_health(manager))
        window.refresh()
        assert manager.state == State.RUNNING and manager.bind_host == "0.0.0.0"
        assert manager.user_url == "http://192.168.1.5:8848"
        assert window.access_card.value.text() == "局域网共享"
        assert "已保存配置一致" in window.network_panel.current.text()
    finally:
        window.ui_timer.stop(); window.tray.hide(); window.hide(); window.deleteLater()


def test_late_setup_reply_from_foreign_service_cannot_restore_old_account_state(manager, runtime_health):
    class Reply:
        aborted = False
        def abort(self): self.aborted = True
        def error(self): return QNetworkReply.NetworkError.NoError
        def readAll(self): return b'{"initialized":true}'
        def deleteLater(self): pass
    manager.accept_health(runtime_health(manager))
    reply = Reply(); manager._setup_reply = reply; manager._setup_identity = manager.runtime_info.copy()
    manager.accept_health({"status": "ok", "version": VERSION})
    assert reply.aborted
    manager._health_finished(reply)
    assert manager.initialized is None and manager.state == State.OTHER


def test_brand_is_shared_by_wizard_window_tray_and_notification(runtime, manager, qt_app, monkeypatch):
    from control_center.brand import ICON_PATH, PRODUCT_TITLE, product_icon
    from control_center.first_run import FirstRunWizard
    from control_center.main_window import MainWindow
    assert struct.unpack("<HHH", ICON_PATH.read_bytes()[:6]) == (0, 1, 7)
    icon = product_icon(); assert not icon.isNull()
    assert {s.width() for s in icon.availableSizes()} == {16, 24, 32, 48, 64, 128, 256}
    wizard = FirstRunWizard(runtime, InstallationStore(runtime, allow_temporary=True))
    window = MainWindow(manager)
    messages = []
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    monkeypatch.setattr(window.tray, "showMessage", lambda *args: messages.append(args))
    try:
        expected = icon.pixmap(32).toImage()
        for value in (wizard.windowIcon(), window.windowIcon(), window.tray.icon()):
            assert value.pixmap(32).toImage() == expected
        window.show(); window.close(); qt_app.processEvents()
        assert messages[0][0] == PRODUCT_TITLE and ".exe" not in messages[0][0]
        assert messages[0][2].pixmap(32).toImage() == expected
        assert PRODUCT_TITLE in window.tray.toolTip()
    finally:
        window.ui_timer.stop(); window.tray.hide(); window.hide(); window.deleteLater()
        wizard.network_panel.checker.stop(); wizard.hide(); wizard.deleteLater()


def test_windows_brand_adapter_never_registers_development(runtime):
    from control_center.brand import configure_windows_brand
    class Adapter:
        calls = []
        def set_process_id(self): self.calls.append("process")
        def register_display(self): self.calls.append("product")
    fake = Adapter(); configure_windows_brand(runtime, fake)
    assert fake.calls == ["process"]
    configure_windows_brand(replace(runtime, layout="portable"), fake)
    assert fake.calls == ["process", "process", "product"]
