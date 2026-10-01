"""Deployment operations use isolated files and mock network replies only."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services.sqlite_backup import BackupService, AUTO_NAME, MANUAL_NAME, check_database
from control_center.config_store import ConfigStore, DeploymentSettings, ConfigError, normalize_remote_url


def test_config_missing_roundtrip_and_retention(tmp_path):
    path = tmp_path / "config/seedlab.json"
    store = ConfigStore(path)
    assert store.load() == DeploymentSettings() and not path.exists()
    for retention in (1, 14, 90):
        expected = DeploymentSettings(access_mode="remote", remote_url=" https://EXAMPLE.org/// ",
                                      auto_backup_retention=retention)
        store.save(expected)
        assert ConfigStore(path).load() == expected
        assert json.loads(path.read_text()) == expected.to_dict()
    assert not list(path.parent.glob("*.tmp"))


@pytest.mark.parametrize("text", ['{', '{"schema_version":2}', '{"unexpected":1}',
    '{"auto_backup_retention":0}', '{"auto_backup_retention":91}', '{"port":true}',
    '{"auto_backup_enabled":1}', '{"lan_address":"invalid"}'])
def test_corrupt_config_preserved_until_explicit_save(tmp_path, text):
    path = tmp_path / "seedlab.json"
    path.write_text(text)
    store = ConfigStore(path)
    assert store.load() == DeploymentSettings()
    assert store.warning and path.read_text() == text
    store.save(DeploymentSettings())
    assert not store.warning and ConfigStore(path).load() == DeploymentSettings()


def test_atomic_failure_preserves_previous_file_and_memory(tmp_path, monkeypatch):
    import control_center.config_store as module
    store = ConfigStore(tmp_path / "seedlab.json")
    store.save(DeploymentSettings())
    before = store.path.read_bytes()
    monkeypatch.setattr(module.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("denied")))
    with pytest.raises(OSError):
        store.save(DeploymentSettings(auto_backup_retention=7))
    assert store.path.read_bytes() == before and store.settings.auto_backup_retention == 14
    assert list(tmp_path.iterdir()) == [store.path]


@pytest.mark.parametrize("url", ["http://example.org", "file:///tmp/a", "javascript:alert(1)",
    "https://user:secret@example.org", "https://example.org/path", "https://example.org?x=1",
    "https://example.org#fragment", "https://example.org?", "https://example.org#",
    "https://example.org:0", "https://example.org:65536", "https://bad host", "https://a\\b"])
def test_remote_rejects_non_root_https(url):
    with pytest.raises(ConfigError):
        normalize_remote_url(url)


def test_network_modes_and_remote_health_results():
    pytest.importorskip("PySide6")
    from control_center.network_service import remote_result, usable_ipv4, resolve_lan, LanAddress
    from app.version import VERSION
    local = DeploymentSettings()
    lan = replace(local, access_mode="lan", lan_address="192.168.1.23")
    remote = replace(local, access_mode="remote", remote_url=" https://EXAMPLE.org:443/// ")
    assert local.bind_host == remote.bind_host == "127.0.0.1" and lan.bind_host == "0.0.0.0"
    assert local.health_url == lan.health_url == remote.health_url == "http://127.0.0.1:8848"
    assert lan.user_url == "http://192.168.1.23:8848"
    assert remote.user_url == "https://example.org:443" and remote.cookie_secure
    assert not local.cookie_secure and not lan.cookie_secure
    assert normalize_remote_url("https://[::1]:9443/") == "https://[::1]:9443"
    assert remote_result({"status":"ok", "version":VERSION})[0] == "ok"
    assert remote_result({"status":"ok", "version":"other"})[0] == "wrong-version"
    assert remote_result({"status":"ok"})[0] == "wrong-site"
    assert remote_result(None, network_error=True)[0] == "unreachable"
    assert all(not usable_ipv4(value) for value in ("127.0.0.1", "0.0.0.0", "169.254.1.2", "invalid"))
    addresses = [LanAddress("Ethernet", "192.168.2.12")]
    resolved, warning = resolve_lan(lan, addresses)
    assert resolved.lan_address == "192.168.2.12" and warning
    assert lan.lan_address == "192.168.1.23"  # Recommendation never saves itself.
    assert resolve_lan(lan, [])[0].user_url is None


@pytest.fixture
def wal_database(tmp_path):
    path = tmp_path / "live.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript("CREATE TABLE species(id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE counts(species_id INTEGER REFERENCES species(id), count INTEGER);"
        "INSERT INTO species VALUES(1,'狗尾草'); INSERT INTO counts VALUES(1,0);")
    connection.commit()
    yield path, connection
    connection.close()


def test_live_wal_snapshot_zero_unicode_manual_collision_and_daily_clock(tmp_path, wal_database):
    source, live = wal_database
    day = [datetime(2026, 10, 1, 16, tzinfo=timezone.utc)]  # Shanghai already Oct 2.
    service = BackupService(tmp_path / "backups", clock=lambda: day[0])
    assert Path(str(source) + "-wal").exists()
    manual = service.snapshot(source)
    collision = service.snapshot(source)
    assert MANUAL_NAME.fullmatch(manual.path.name) and manual.path != collision.path
    auto = service.daily(source)
    assert AUTO_NAME.fullmatch(auto.path.name)[1] == "20261002"
    assert service.daily(source).created is False
    day[0] += timedelta(days=1)
    assert service.daily(source).created
    for result in (manual, collision, auto):
        assert check_database(result.path, immutable=True).valid
        with closing(sqlite3.connect(result.path)) as backup:
            assert backup.execute("SELECT name,count FROM species JOIN counts ON id=species_id").fetchone() == ("狗尾草", 0)
    assert live.execute("SELECT count FROM counts").fetchone() == (0,)
    assert (service.root / "before-upgrade").is_dir()


def test_invalid_foreign_key_snapshot_and_missing_source_leave_no_partial(tmp_path, monkeypatch, wal_database):
    source, _ = wal_database
    service = BackupService(tmp_path / "backups")
    # Force an actual bad snapshot rather than merely mirroring the implementation.
    with closing(sqlite3.connect(source)) as bad:
        bad.execute("INSERT INTO counts VALUES(999,1)")
        bad.commit()
    with pytest.raises(sqlite3.DatabaseError):
        service.snapshot(source)
    assert not list(service.root.rglob("*.db")) and not list(service.root.rglob("*.partial-*"))
    with pytest.raises(sqlite3.Error):
        service.snapshot(tmp_path / "missing.db")
    assert not (tmp_path / "missing.db").exists()


def test_retention_counts_valid_snapshots_and_protects_others(tmp_path, wal_database):
    source, _ = wal_database
    day = [datetime(2026, 9, 1)]
    service = BackupService(tmp_path / "backups", clock=lambda: day[0])
    manual = service.snapshot(source)
    for _ in range(17):
        service.snapshot(source, "auto")
        day[0] += timedelta(days=1)
    directory = service.root / "auto"
    unknown = directory / "other.db"
    unknown.write_text("unknown")
    invalid = directory / "seedlab-auto-20260101-010000.db"
    invalid.write_text("invalid")
    sidecar = directory / "seedlab-auto-20260102-010000.db"
    sidecar.write_bytes(manual.path.read_bytes())
    Path(str(sidecar) + "-wal").write_bytes(b"do not touch")
    history = service.root / "dev-reset.db"
    history.write_text("historical")
    before_upgrade = service.root / "before-upgrade/historical.db"
    before_upgrade.write_text("historical")
    assert len(service.prune(14)) == 3 and len(service.candidates("auto")) == 14
    for protected in (manual.path, unknown, invalid, sidecar, history, before_upgrade):
        assert protected.exists()
    assert not list(directory.glob("*-shm"))


def test_symlink_snapshot_never_pruned_and_redirected_directory_refused(tmp_path, wal_database):
    source, _ = wal_database
    service = BackupService(tmp_path / "backups")
    service.prepare()
    link = service.root / "auto/seedlab-auto-20260101-010000.db"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("Windows account cannot create symbolic links")
    assert service.prune(1) == [] and link.is_symlink()
    other = tmp_path / "redirected"
    other.symlink_to(service.root, target_is_directory=True)
    with pytest.raises(OSError):
        BackupService(other).snapshot(source)


@pytest.fixture
def desktop(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from control_center.paths import RuntimePaths
    from control_center.server_manager import ServerProcessManager
    app = QApplication.instance() or QApplication([])
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("test")
    paths = RuntimePaths(tmp_path, Path(sys.executable), web, tmp_path / "database.db",
                         tmp_path / "bootstrap.token", tmp_path / "logs")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/run_prod.py").write_text("# Isolated mock launcher")
    manager = ServerProcessManager(paths, polling=False)
    yield app, manager
    manager.stop_checks()
    for logger in (manager.control_log, manager.server_log):
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


def wait_job(app, operations):
    deadline = time.monotonic() + 5
    while operations.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert not operations.busy


def test_manager_snapshot_external_and_owned_settings(desktop, runtime_health, monkeypatch):
    from control_center.server_manager import State
    from app.version import VERSION
    app, manager = desktop
    monkeypatch.setattr(manager, "_port_free", lambda: True)
    manager.accept_health(runtime_health(manager))
    manager.apply_settings(DeploymentSettings(access_mode="remote", remote_url="https://example.org"))
    assert manager.state == State.EXTERNAL and manager.user_url == "http://127.0.0.1:8848"
    assert manager.config.access_mode == "remote" and not manager.can_stop
    manager.accept_health(None)
    assert manager.user_url == "https://example.org" and manager.state == State.STOPPED
    manager.apply_settings(DeploymentSettings())
    manager.process = type("Child", (), {"poll":lambda self: None})()
    manager.running_config = DeploymentSettings()
    manager.state = State.RUNNING
    with pytest.raises(ConfigError):
        manager.apply_settings(DeploymentSettings(access_mode="remote", remote_url="https://example.org"))
    assert manager.active_config.access_mode == "local"
    manager.process = None


def test_network_launch_environment_and_missing_lan(desktop, monkeypatch, runtime_health):
    from io import StringIO
    import control_center.server_manager as module
    from control_center.network_service import LanAddress
    app, manager = desktop
    launches = []
    class Child:
        stdout = StringIO("")
        pid = 9
        def poll(self): return None
    monkeypatch.setattr(module.subprocess, "Popen", lambda command, **kwargs: (launches.append((command, kwargs)) or Child()))
    monkeypatch.setattr(manager, "_port_free", lambda: True)
    monkeypatch.setattr(manager, "poll_health", lambda: None)
    monkeypatch.setattr(module, "lan_addresses", lambda: [])
    manager.apply_settings(DeploymentSettings(access_mode="lan"))
    manager.start()
    assert not launches and "没有可用" in manager.message
    monkeypatch.setattr(module, "lan_addresses", lambda: [LanAddress("Ethernet", "192.168.1.4")])
    for mode in ("lan", "remote", "local"):
        manager.apply_settings(DeploymentSettings(access_mode=mode, remote_url="https://example.org" if mode == "remote" else None))
        manager.start()
        manager.accept_health(None)
        command, parameters = launches[-1]
        assert command[4] == ("0.0.0.0" if mode == "lan" else "127.0.0.1")
        assert parameters["env"]["SEEDLAB_COOKIE_SECURE"] == ("true" if mode == "remote" else "false")
        assert parameters["env"]["SEEDLAB_ENV"] == "production"
        assert parameters["env"]["SEEDLAB_DATABASE_URL"].endswith("database.db")
        if mode == "lan":
            assert manager.config.lan_address is None and manager.active_config.lan_address == "192.168.1.4"
            manager.accept_health(runtime_health(manager))
            manager.apply_settings(replace(manager.config, auto_backup_retention=7))
            assert manager.config.auto_backup_retention == 7
        manager.process = None
        manager.running_config = None
        manager.state = module.State.STOPPED


def test_background_auto_failure_keeps_owned_running_and_external_is_skipped(desktop):
    from control_center.operations import Operations
    from control_center.server_manager import State
    app, manager = desktop
    operations = Operations(manager)
    manager.state = State.EXTERNAL
    manager.changed.emit()
    assert not operations.busy and not manager.paths.backups.exists()
    manager.process = object()
    manager.state = State.RUNNING
    manager.changed.emit()
    wait_job(app, operations)
    assert manager.state == State.RUNNING and manager.process is not None
    assert "自动备份失败" in operations.error
    manager.process = None


def test_ui_drafts_save_current_access_and_clipboard_without_readback(desktop, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from control_center.main_window import MainWindow
    from control_center.network_service import LanAddress
    import control_center.widgets.operations_panels as panels
    app, manager = desktop
    monkeypatch.setattr(panels, "lan_addresses", lambda: [LanAddress("Ethernet", "192.168.1.5")])
    window = MainWindow(manager)
    network = window.network_panel
    assert set(network.modes) == {"local", "lan", "remote"} and network.mode == "local"
    assert not network.dirty
    network.modes["lan"].setChecked(True)
    window.select_page(5)
    window.refresh()
    assert network.mode == "lan" and network.dirty
    network.save()
    assert manager.config.access_mode == "lan" and not network.dirty
    assert window.access_card.value.text() == "局域网共享"
    network.modes["remote"].setChecked(True)
    network.remote_edit.setText("https://example.org/")
    network.save()
    assert manager.user_url == "https://example.org" and network.check_button.text() == "检测远程连接"
    assert window.access_card.value.text() == "远程访问"
    window.settings_panel.retention.setValue(7)
    window.settings_panel.save_button.click()
    assert ConfigStore(manager.paths.config_file).load().auto_backup_retention == 7
    assert window.backup_panel.check_button.text() == "立即检查"
    assert window.backup_panel.backup_button.text() == "立即备份"
    copied = []
    class Clipboard:
        def setText(self, value): copied.append(value)
        def text(self): pytest.fail("Immediate clipboard readback is prohibited")
    monkeypatch.setattr(QApplication, "clipboard", lambda: Clipboard())
    network.copy_address()
    window.token_edit.setText("temporary-token")
    window.copy_token()
    assert copied == ["https://example.org", "temporary-token"]
    window.network_panel.timer.stop()
    window.ui_timer.stop()
    window.tray.hide()
    window.deleteLater()


def test_async_remote_reply_classification_timeout_and_event_dedup(desktop, monkeypatch):
    from PySide6.QtNetwork import QNetworkRequest, QNetworkReply
    from control_center.network_service import RemoteChecker
    from app.version import VERSION
    app, manager = desktop
    checker = RemoteChecker(manager.control_log)
    requests, events = [], []
    class Reply:
        payload = {"status":"ok", "version":VERSION}
        code = 200
        failure = QNetworkReply.NetworkError.NoError
        def error(self): return self.failure
        def attribute(self, _): return self.code
        def readAll(self): return json.dumps(self.payload).encode()
        def deleteLater(self): pass
        def errorString(self): return "simulated network failure"
        def abort(self): pass
    reply = Reply()
    monkeypatch.setattr(checker.network, "get", lambda request: (requests.append(request) or reply))
    checker.event.connect(events.append)
    for _ in range(2):
        checker.check("https://example.org", manual=False)
        checker._finished(reply)
    assert len(events) == 1 and checker.status == "ok"
    assert requests[0].transferTimeout() == 5000
    assert requests[0].url().toString() == "https://example.org/api/health"
    assert requests[0].attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute) == QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
    reply.payload["version"] = "other"
    checker.check("https://example.org")
    checker._finished(reply)
    assert checker.status == "wrong-version"
    reply.code = 404
    reply.failure = QNetworkReply.NetworkError.ContentNotFoundError
    checker.check("https://example.org")
    checker._finished(reply)
    assert checker.status == "wrong-site"
    reply.code = None
    reply.failure = QNetworkReply.NetworkError.SslHandshakeFailedError
    checker.check("https://example.org")
    checker._finished(reply)
    assert checker.status == "unreachable"
    checker.check("https://example.org")
    count = len(events)
    checker.reset()
    checker._finished(reply)
    assert checker.status == "unchecked" and len(events) == count


def test_dirty_exit_saves_both_panels_and_corrupt_config_warning_clears(desktop, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from control_center.main_window import MainWindow
    app, manager = desktop
    manager.paths.config_file.parent.mkdir(exist_ok=True)
    manager.paths.config_file.write_text("broken")
    manager.config_store.load()
    window = MainWindow(manager)
    assert "安全模式" in window.settings_panel.warning.text()
    assert "安全模式" in window.network_panel.warning_label.text()
    window.network_panel.modes["remote"].setChecked(True)
    window.network_panel.remote_edit.setText("https://example.org")
    window.settings_panel.retention.setValue(9)
    window.select_page(1)
    window.refresh()
    assert window.network_panel.dirty and window.settings_panel.dirty
    exits = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: next(b for b in self.buttons() if b.text() == "保存"))
    monkeypatch.setattr(window, "finish_exit", lambda: exits.append(True))
    window.request_exit()
    saved = ConfigStore(manager.paths.config_file).load()
    assert saved.access_mode == "remote" and saved.auto_backup_retention == 9 and exits == [True]
    assert not window.settings_panel.warning.text() and not window.network_panel.warning_label.text()
    window.network_panel.timer.stop()
    window.ui_timer.stop()
    window.tray.hide()
    window.deleteLater()
