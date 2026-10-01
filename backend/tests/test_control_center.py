"""Desktop smoke and process ownership tests, with isolated paths only."""
import asyncio
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timedelta
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
from control_center.log_utils import make_logger, user_log_tail, format_event
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
    for index, nav in enumerate(window.nav_buttons):
        assert not nav.icon().isNull() and nav.iconSize().width() == 18
        nav.click()
        assert window.pages.currentIndex() == index and nav.isChecked()
        assert sum(item.isChecked() for item in window.nav_buttons) == 1
    window.select_page(0)
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


def test_management_grid_refreshes_service_fields(manager, qt_app):
    window = MainWindow(manager)
    window.select_page(1)
    manager.process = Child()
    manager.state = State.RUNNING
    manager.health_ok = True
    manager.started_at = datetime.now() - timedelta(minutes=2)
    window.refresh()
    values = window.management_grid.values
    assert len(values) == 8
    assert values["status"].text() == "正在运行"
    assert values["pid"].text() == "12345"
    assert values["host"].text() == "127.0.0.1" and values["port"].text() == "8848"
    assert values["version"].text() == f"v{VERSION}" and values["health"].text() == "正常"
    assert values["started"].text() == manager.started_at.strftime("%Y-%m-%d %H:%M:%S")
    assert values["elapsed"].text().startswith("00:02:")
    assert "正在运行" in window.management_state.text()
    manager.process = None
    manager.state = State.STOPPED
    manager.health_ok = False
    manager.started_at = None
    window.refresh()
    assert values["pid"].text() == "—" and values["health"].text() == "未运行"
    window.ui_timer.stop()
    window.tray.hide()
    window.deleteLater()


def test_overview_only_keeps_three_important_events(manager, qt_app):
    window = MainWindow(manager)
    assert window.recent_events.text() == "最近没有需要处理的问题。"
    messages = ("SeedLab 启动成功。", "SeedLab 已停止。", "服务意外退出，请查看日志后重试。", "健康检查已恢复。")
    for message in messages:
        window.add_event(message)
    window.add_event("健康检查完成")
    window.add_event("正在启动 SeedLab。")
    assert len(window.events) == 3
    text = window.recent_events.text()
    assert len(text.splitlines()) == 3
    assert "启动成功" not in text and "健康检查完成" not in text
    assert text.splitlines()[0].endswith("健康检查已恢复")
    assert text.splitlines()[0].startswith(datetime.now().strftime("%H:%M"))
    window.ui_timer.stop()
    window.tray.hide()
    window.deleteLater()


def test_event_log_uses_readable_times_without_changing_full_file(tmp_path):
    now = datetime(2026, 10, 2, 17, 0)
    path = tmp_path / "events.log"
    original = ("2026-10-01 16:05:05,658 INFO [事件] SeedLab 已停止。\n"
                "2026-10-02 16:09:42,911 INFO [事件] SeedLab 启动成功。\n"
                "2026-10-02 16:09:43,123 INFO technical details\n")
    path.write_text(original, encoding="utf-8")
    assert user_log_tail(path, now=now).splitlines() == [
        "16:09:42    SeedLab 启动成功", "10-01 16:05    SeedLab 已停止"]
    assert user_log_tail(path, limit=1, now=now) == "16:09:42    SeedLab 启动成功"
    assert path.read_text(encoding="utf-8") == original
    assert format_event(datetime(2026, 10, 2, 16, 9), "启动成功。", overview=True, now=now) == "16:09    启动成功"


@pytest.mark.parametrize("width,height,scale", [(1366,768,1), (1366,768,1.25), (1920,1080,1), (1920,1080,1.25)])
def test_window_fits_available_screen(width, height, scale):
    available_width, available_height = int(width / scale), int((height - 48) / scale)
    target, minimum = window_dimensions(available_width, available_height)
    assert target[0] < available_width and target[1] < available_height
    assert minimum[0] <= target[0] and minimum[1] <= target[1]
