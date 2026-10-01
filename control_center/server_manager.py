"""Process ownership, asynchronous health checks and graceful lifecycle."""
from datetime import datetime
from enum import Enum
import json
import os
import socket
import subprocess
import threading
import time

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

from app.version import VERSION
from .log_utils import make_logger
from .paths import RuntimePaths


class State(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"
    EXTERNAL = "external"


STATE_LABELS = {State.STOPPED: "已停止", State.STARTING: "正在启动", State.RUNNING: "正在运行",
                State.STOPPING: "正在停止", State.ERROR: "启动失败", State.EXTERNAL: "检测到 SeedLab 已在运行"}


class ServerProcessManager(QObject):
    changed = Signal()
    event = Signal(str)
    stop_timed_out = Signal()
    _output_error = Signal(str)
    HOST = "127.0.0.1"
    PORT = 8848

    def __init__(self, paths: RuntimePaths | None = None, parent=None, *, polling=True):
        super().__init__(parent)
        self.paths = paths or RuntimePaths.discover()
        self.polling = polling
        self.state = State.STOPPED
        self.process = None
        self.stop_file = None
        self.health_ok = False
        self.started_at = None
        self.message = "服务尚未启动，点击启动即可开始使用。"
        self.restart_pending = False
        self.pending_start = False
        self._reply = None
        self._setup_reply = None
        self.initialized = None
        self._started_clock = 0.0
        self._stop_clock = None
        self._timeout_notified = False
        self._failure_reason = ""
        self.start_timeout = 20.0
        self.stop_timeout = 10.0
        self.control_log = make_logger(self.paths.logs, "control-center")
        self.server_log = make_logger(self.paths.logs, "production-server")
        self._output_error.connect(self._remember_error)
        self.network = QNetworkAccessManager(self)
        self.network.finished.connect(self._health_finished)
        self.health_timer = QTimer(self)
        self.health_timer.setInterval(1500)
        self.health_timer.timeout.connect(self.poll_health)
        self.process_timer = QTimer(self)
        self.process_timer.setInterval(250)
        self.process_timer.timeout.connect(self.tick)
        if polling:
            self.health_timer.start()
            self.process_timer.start()
            QTimer.singleShot(0, self.poll_health)

    @property
    def url(self):
        return f"http://{self.HOST}:{self.PORT}"

    @property
    def label(self):
        return "正在重启" if self.restart_pending and self.state != State.ERROR else STATE_LABELS[self.state]

    @property
    def can_start(self):
        return self.process is None and not self.pending_start and self.state in {State.STOPPED, State.ERROR}

    @property
    def can_stop(self):
        return self.process is not None and self.state in {State.RUNNING, State.ERROR}

    @property
    def can_open(self):
        return self.state in {State.RUNNING, State.EXTERNAL} and self.health_ok

    def _event(self, message):
        self.control_log.info("[事件] %s", message)
        self.event.emit(message)

    def _set_state(self, state, message):
        if state == State.ERROR and (state != self.state or message != self.message):
            self._event(message)
        self.state = state
        self.message = message
        self.changed.emit()

    def _port_free(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                if os.name == "nt":
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind((self.HOST, self.PORT))
            return True
        except OSError:
            return False

    def poll_health(self):
        if self._reply is not None:
            return
        request = QNetworkRequest(QUrl(self.url + "/api/health"))
        request.setTransferTimeout(1200)
        self._reply = self.network.get(request)

    def _health_finished(self, reply):
        if reply is self._setup_reply:
            self._setup_reply = None
            try:
                payload = json.loads(bytes(reply.readAll())) if reply.error() == QNetworkReply.NetworkError.NoError else None
                self.initialized = payload.get("initialized") if isinstance(payload, dict) else None
            except (ValueError, UnicodeDecodeError):
                self.initialized = None
            reply.deleteLater()
            self.changed.emit()
            return
        if reply is not self._reply:
            reply.deleteLater()
            return
        self._reply = None
        try:
            payload = json.loads(bytes(reply.readAll())) if reply.error() == QNetworkReply.NetworkError.NoError else None
        except (ValueError, UnicodeDecodeError):
            payload = None
        reply.deleteLater()
        self.accept_health(payload)

    def accept_health(self, payload):
        healthy = isinstance(payload, dict) and payload.get("status") == "ok" and payload.get("version") == VERSION
        was_healthy = self.health_ok
        self.health_ok = healthy
        if healthy and self.polling and self._setup_reply is None:
            request = QNetworkRequest(QUrl(self.url + "/api/setup/status"))
            request.setTransferTimeout(1200)
            self._setup_reply = self.network.get(request)
        if self.process is None:
            if healthy:
                self.pending_start = False
                if self.state != State.EXTERNAL:
                    self._event("检测到 SeedLab 已在运行，当前服务由其他入口启动。")
                self._set_state(State.EXTERNAL, "可打开 SeedLab；请在原启动入口停止服务。")
            elif self.pending_start:
                self.pending_start = False
                self._spawn()
            elif self.state == State.EXTERNAL:
                self.initialized = None
                self._set_state(State.STOPPED, "外部服务已停止，可从此处启动。")
            elif not self._port_free():
                self._set_state(State.ERROR, f"端口 {self.PORT} 已被其他程序占用。请关闭占用程序后重试。")
        elif healthy and self.process.poll() is None and self.state not in {State.STOPPING, State.ERROR}:
            if self.state == State.STARTING:
                self.started_at = datetime.now()
                self.restart_pending = False
                self._event("SeedLab 启动成功。")
                self.server_log.info("[事件] SeedLab 启动成功。")
            elif not was_healthy:
                self._event("健康检查已恢复。")
            self._set_state(State.RUNNING, "SeedLab 正常运行，可打开浏览器开始实验工作。")
        self.changed.emit()

    def start(self):
        if not self.can_start:
            return
        if not self.paths.python.is_file():
            self._set_state(State.ERROR, "运行环境缺失，请先安装项目的 Python 依赖。")
            return
        if not (self.paths.web_root / "index.html").is_file():
            self._set_state(State.ERROR, "前端生产文件缺失，请先构建前端后重试。")
            return
        self.pending_start = True
        self._started_clock = time.monotonic()
        self._failure_reason = ""
        self._set_state(State.STARTING, "正在准备服务并检查数据库，请稍候。")
        self.poll_health()

    def _spawn(self):
        if not self._port_free():
            self._set_state(State.ERROR, f"端口 {self.PORT} 已被其他程序占用。请关闭占用程序后重试。")
            return
        try:
            self.stop_file = self.paths.new_stop_file()
            environment = os.environ.copy()
            environment.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", SEEDLAB_ENV="production")
            self.process = subprocess.Popen(self.paths.command(self.stop_file, self.HOST, self.PORT),
                cwd=self.paths.root, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self._event("正在启动 SeedLab。")
            self.server_log.info("[事件] 正在启动 SeedLab。")
            threading.Thread(target=self._capture_output, args=(self.process,), daemon=True).start()
        except OSError:
            self.control_log.exception("隐藏服务启动失败")
            self.process = None
            self._set_state(State.ERROR, "服务启动失败，请查看日志并检查运行环境。")

    def _capture_output(self, process):
        try:
            with process.stdout:
                for line in process.stdout:
                    self.server_log.info(line.rstrip())
                    for marker, reason in (("数据库升级失败", "数据库升级失败，请查看日志并保留现有数据库。"),
                                           ("前端生产文件缺失", "前端生产文件缺失，请先构建前端。"),
                                           ("address already in use", f"端口 {self.PORT} 已被其他程序占用。")):
                        if marker in line:
                            self._output_error.emit(reason)
        except Exception:
            self.server_log.exception("服务日志读取失败")

    def _remember_error(self, reason):
        self._failure_reason = reason

    def stop(self):
        if self.process is None:
            self.pending_start = False
            if self.state != State.EXTERNAL:
                self._set_state(State.STOPPED, "服务已停止。")
            return
        if self.state == State.STOPPING:
            return
        try:
            self.stop_file.touch()
        except OSError:
            self.control_log.exception("停止请求写入失败")
            self._set_state(State.ERROR, "无法发送停止请求，请查看日志并检查临时目录权限。")
            return
        self._stop_clock = time.monotonic()
        self._timeout_notified = False
        self._set_state(State.STOPPING, "正在完成当前请求并关闭服务，请稍候。")
        self._event("已请求正常停止 SeedLab。")

    def restart(self):
        if self.can_stop:
            self.restart_pending = True
            self.stop()

    def continue_waiting(self):
        self._stop_clock = time.monotonic()
        self._timeout_notified = False

    def force_stop(self):
        if self.process is not None:
            self.restart_pending = False
            self._event("用户选择强制结束服务。")
            if os.name == "nt":
                subprocess.Popen(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                                 creationflags=subprocess.CREATE_NO_WINDOW,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                self.process.kill()

    def tick(self):
        if self.process is not None:
            code = self.process.poll()
            if code is not None:
                stopped = self.state == State.STOPPING
                restart = self.restart_pending and stopped
                self.process = None
                self.health_ok = False
                self.started_at = None
                self.initialized = None
                if self.stop_file:
                    self.stop_file.unlink(missing_ok=True)
                self.stop_file = None
                if stopped:
                    self._set_state(State.STOPPED, "服务已正常停止。")
                    self._event("SeedLab 已停止。")
                    self.server_log.info("[事件] SeedLab 已停止。")
                else:
                    self.restart_pending = False
                    reason = self._failure_reason or "服务意外退出，请查看日志后重试。"
                    self._set_state(State.ERROR, reason)
                if restart:
                    QTimer.singleShot(0, self.start)
            elif self.state == State.STOPPING and self._stop_clock is not None:
                if time.monotonic() - self._stop_clock >= self.stop_timeout and not self._timeout_notified:
                    self._timeout_notified = True
                    self.stop_timed_out.emit()
            elif self.state == State.STARTING and time.monotonic() - self._started_clock >= self.start_timeout:
                self._set_state(State.ERROR, "服务启动后未通过健康检查，请查看日志或先停止服务再重试。")
        elif self.pending_start and time.monotonic() - self._started_clock >= self.start_timeout:
            self.pending_start = False
            self._set_state(State.ERROR, "服务启动前无法完成检查，请重试。")

    def stop_checks(self):
        self.health_timer.stop()
        self.process_timer.stop()
        if self._reply is not None:
            self._reply.abort()
        if self._setup_reply is not None:
            self._setup_reply.abort()
