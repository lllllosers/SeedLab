"""Desktop smoke and process ownership tests, with isolated paths only."""
import asyncio
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import time
import importlib.util
from io import StringIO

import pytest

pytest.importorskip("PySide6")  # Server-only installs do not require the control extra.
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QLineEdit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.version import VERSION
from control_center.paths import RuntimePaths
from control_center.server_manager import ServerProcessManager, State
from control_center.main_window import MainWindow
from control_center.log_utils import make_logger, user_log_tail
from control_center.theme import window_dimensions


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def paths(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>test</html>", encoding="utf-8")
    return RuntimePaths(ROOT, Path(sys.executable), web, tmp_path / "isolated.db",
                        tmp_path / "bootstrap.token", tmp_path / "logs")


@pytest.fixture
def manager(qt_app, paths):
    result = ServerProcessManager(paths, polling=False)
    yield result
    result.stop_checks()
    for logger in (result.server_log, result.control_log):
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


class Child:
    pid = 12345
    code = None
    def poll(self):
        return self.code
    def kill(self):
        pytest.fail("Must not kill a child during ordinary graceful stop")


def test_command_defaults_and_unique_temp_control_path(paths):
    one, two = paths.new_stop_file(), paths.new_stop_file()
    assert one != two and not one.exists()
    assert one.is_relative_to(Path(tempfile.gettempdir()))
    command = paths.command(one)
    assert command[:3] == [str(paths.python), "-u", str(ROOT / "scripts/run_prod.py")]
    assert command[3:7] == ["--host", "127.0.0.1", "--port", "8848"]
    assert command[-2:] == ["--stop-file", str(one)]


def test_external_health_is_not_owned_and_disappears(manager, monkeypatch):
    monkeypatch.setattr(manager, "_port_free", lambda: True)
    manager.accept_health({"status": "ok", "version": VERSION})
    assert manager.state == State.EXTERNAL
    assert manager.can_open and not manager.can_start and not manager.can_stop
    manager.stop()
    assert manager.state == State.EXTERNAL and manager.process is None
    manager.accept_health(None)
    assert manager.state == State.STOPPED


def test_foreign_port_and_wrong_version_are_not_seedlab(manager, monkeypatch):
    monkeypatch.setattr(manager, "_port_free", lambda: False)
    for payload in ({"status": "ok", "version": "wrong"}, {"status": "not-seedlab"}, None):
        manager.accept_health(payload)
        assert manager.state == State.ERROR
        assert "已被其他程序占用" in manager.message
        assert not manager.can_open and manager.process is None


def test_graceful_stop_and_child_exit_cleanup(manager):
    manager.process = Child()
    child = manager.process
    manager.state = State.RUNNING
    manager.stop_file = manager.paths.new_stop_file()
    signal_file = manager.stop_file
    manager.stop()
    assert signal_file.is_file() and manager.state == State.STOPPING
    assert not manager.can_start and not manager.can_stop
    child.code = 0
    manager.tick()
    assert manager.process is None and manager.state == State.STOPPED
    assert not signal_file.exists()


def test_stop_timeout_waits_for_user_without_killing(manager):
    manager.process = Child()
    manager.state = State.RUNNING
    manager.stop_file = manager.paths.new_stop_file()
    manager.stop()
    notifications = []
    manager.stop_timed_out.connect(lambda: notifications.append(True))
    manager._stop_clock = time.monotonic() - manager.stop_timeout - 1
    manager.tick()
    manager.tick()
    assert notifications == [True]
    assert manager.state == State.STOPPING and manager.process is not None
    manager.continue_waiting()
    manager.tick()
    assert notifications == [True]
    manager.stop_file.unlink()


def test_unexpected_child_exit_allows_retry(manager):
    manager.process = Child()
    manager.process.code = 1
    manager.state = State.STARTING
    manager.tick()
    assert manager.state == State.ERROR and manager.process is None and manager.can_start


def test_start_is_single_and_requires_production_files(manager, monkeypatch):
    monkeypatch.setattr(manager, "poll_health", lambda: None)
    manager.start()
    assert manager.pending_start and manager.state == State.STARTING
    manager.start()
    assert manager.process is None  # One preflight, not repeated spawns.
    manager.stop()
    manager.paths = replace(manager.paths, web_root=manager.paths.web_root / "missing")
    manager.start()
    assert manager.state == State.ERROR and "前端生产文件缺失" in manager.message


def test_hidden_launch_then_restart_waits_for_exit(manager, monkeypatch, qt_app):
    import os
    import control_center.server_manager as module
    launches = []
    children = []
    def spawn(command, **kwargs):
        launches.append((command, kwargs))
        child = Child()
        child.stdout = StringIO("SeedLab Bootstrap Token: process-secret\n")
        children.append(child)
        return child
    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    monkeypatch.setattr(manager, "_port_free", lambda: True)
    monkeypatch.setattr(manager, "poll_health", lambda: None)
    manager.start()
    manager.accept_health(None)
    assert len(launches) == 1
    assert launches[0][1]["creationflags"] == (module.subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    manager.accept_health({"status": "ok", "version": VERSION})
    assert manager.state == State.RUNNING
    manager.restart()
    assert len(launches) == 1 and manager.state == State.STOPPING
    children[0].code = 0
    manager.tick()
    qt_app.processEvents()
    manager.accept_health(None)
    assert len(launches) == 2  # Only after the old owned process exited.
    manager.stop()
    children[1].code = 0
    manager.tick()
    assert manager.state == State.STOPPED


def test_runner_stop_file_requests_exit_and_cleans_up(tmp_path):
    spec = importlib.util.spec_from_file_location("stop_runner", ROOT / "scripts/run_prod.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    stop = tmp_path / "test.stop"
    class Server:
        should_exit = False
        async def serve(self):
            stop.touch()
            while not self.should_exit:
                await asyncio.sleep(0.01)
    server = Server()
    asyncio.run(runner.serve_with_stop_file(server, stop))
    assert server.should_exit and not stop.exists()


def test_utf8_rotating_logs_redact_secrets_and_show_event_summary(paths):
    logger = make_logger(paths.logs, "secrets-test")
    try:
        logger.info("SeedLab Bootstrap Token: bootstrap-secret-value")
        logger.info('payload: {"password": "password-secret", "session_token": "session-secret"}')
        logger.info("[事件] 服务已正常停止。")
        content = (paths.logs / "secrets-test.log").read_text(encoding="utf-8")
        for secret in ("bootstrap-secret-value", "password-secret", "session-secret"):
            assert secret not in content
        assert "已隐藏" in content
        assert "服务已正常停止" in user_log_tail(paths.logs / "secrets-test.log")
        handler = logger.handlers[0]
        assert handler.maxBytes == 5 * 1024 ** 2 and handler.backupCount == 2
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


def test_window_six_pages_tray_close_and_bootstrap(manager, qt_app, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    manager.paths.bootstrap_token.write_text("isolated-token-secret", encoding="utf-8")
    window = MainWindow(manager)
    window.show()
    qt_app.processEvents()
    assert window.pages.count() == 6 and window.pages.currentIndex() == 0
    manager.accept_health({"status": "ok", "version": VERSION})
    window.refresh()
    assert window.bootstrap.isVisible()
    assert window.token_edit.echoMode() == QLineEdit.EchoMode.Password
    clipboard_value = {}
    class Clipboard:
        def setText(self, value):
            clipboard_value["text"] = value
        def text(self):
            return clipboard_value.get("text", "")
    monkeypatch.setattr(QApplication, "clipboard", lambda: Clipboard())
    window.copy_token()
    assert clipboard_value["text"] == "isolated-token-secret"
    assert "初始化码已复制" in window.bootstrap_hint.text()
    window.toggle_token()
    assert window.token_edit.echoMode() == QLineEdit.EchoMode.Normal
    window.toggle_token()
    assert window.token_edit.echoMode() == QLineEdit.EchoMode.Password
    assert window.tray_open.isEnabled() and not window.tray_stop.isEnabled()
    manager.initialized = True
    window.refresh()
    assert not window.bootstrap.isVisible()
    window.close()
    qt_app.processEvents()
    assert not window.isVisible() and window._hidden_notice
    window.restore_window()
    assert window.isVisible()
    window.tray.hide()
    window.hide()
    window.ui_timer.stop()
    window.deleteLater()


@pytest.mark.parametrize("width,height,scale", [(1366,768,1), (1366,768,1.25), (1920,1080,1), (1920,1080,1.25)])
def test_window_fits_available_screen(width, height, scale):
    available_width, available_height = int(width / scale), int((height - 48) / scale)
    target, minimum = window_dimensions(available_width, available_height)
    assert target[0] < available_width and target[1] < available_height
    assert minimum[0] <= target[0] and minimum[1] <= target[1]
