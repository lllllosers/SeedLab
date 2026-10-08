"""Process ownership, asynchronous health checks and graceful lifecycle."""
from datetime import datetime
from dataclasses import replace
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
from .config_store import ConfigStore, ConfigError
from .network_service import lan_addresses, resolve_lan, MODE_LABELS
from app.services.runtime_identity import deployment_identity


class State(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"
    EXTERNAL = "external"
    OTHER = "other-instance"


STATE_LABELS = {State.STOPPED: "已停止", State.STARTING: "正在启动", State.RUNNING: "正在运行",
                State.STOPPING: "正在停止", State.ERROR: "启动失败", State.EXTERNAL: "当前数据的服务由其他入口运行",
                State.OTHER: "检测到另一份 SeedLab 正在运行"}


class ServerProcessManager(QObject):
    changed = Signal()
    event = Signal(str)
    stop_timed_out = Signal()
    _output_error = Signal(str)

    def __init__(self, paths: RuntimePaths | None = None, parent=None, *, polling=True, config_store=None):
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
        self.maintenance = False
        self._reply = None
        self._setup_reply = None
        self.initialized = None
        self.identity = deployment_identity(self.paths.instance_root)
        self.runtime_info = None
        self._setup_identity = None
        self._started_clock = 0.0
        self._stop_clock = None
        self._timeout_notified = False
        self._failure_reason = ""
        self.start_timeout = 20.0
        self.stop_timeout = 10.0
        self.control_log = make_logger(self.paths.logs, "control-center")
        self.server_log = make_logger(self.paths.logs, "production-server")
        self.config_store = config_store or ConfigStore(self.paths.config_file, self.control_log)
        self.config_store.load()
        self.running_config = None
        self.confirmed_url = None
        self.external_port = None
        self.start_config = None
        self.network_warning = self.config_store.warning
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
        return self.health_url

    @property
    def config(self):
        return self.config_store.settings

    @property
    def active_config(self):
        return self.running_config or self.start_config or self.config

    @property
    def bind_host(self):
        if self.state == State.EXTERNAL and self.runtime_info:
            return self.runtime_info["bind_host"]
        return self.active_config.bind_host

    @property
    def port(self):
        return self.external_port if self.state in {State.EXTERNAL, State.OTHER} else self.active_config.port

    @property
    def health_url(self):
        return self.confirmed_url if self.state in {State.EXTERNAL, State.OTHER} else self.active_config.health_url

    @property
    def user_url(self):
        if self.state == State.OTHER:
            return None
        if self.state == State.EXTERNAL:
            return (replace(self.config, port=self.external_port).user_url
                    if self.runtime_info and self.runtime_info["access_mode"] == self.config.access_mode
                    else self.confirmed_url)
        return self.active_config.user_url

    @property
    def mode_label(self):
        if self.state == State.OTHER:
            return "其他部署，当前控制中心不接管"
        mode = self.runtime_info["access_mode"] if self.runtime_info else self.active_config.access_mode
        return MODE_LABELS[mode]

    @property
    def configuration_status(self):
        if self.state == State.OTHER:
            return "请修改当前部署的访问端口，或在原入口停止另一份服务。"
        if self.process is not None or self.state == State.EXTERNAL:
            actual = self.runtime_info or {"access_mode": self.active_config.access_mode,
                                          "port": self.active_config.port, "bind_host": self.active_config.bind_host}
            mismatch = (actual["access_mode"] != self.config.access_mode or actual["port"] != self.config.port
                        or actual["bind_host"] != self.config.bind_host or self.network_settings_changed(self.config))
            return (f"当前运行配置与已保存配置不同；已保存：{MODE_LABELS[self.config.access_mode]}，"
                    f"端口 {self.config.port}。请重启 SeedLab 应用设置。" if mismatch else "当前运行配置与已保存配置一致。")
        return f"下次启动：{MODE_LABELS[self.config.access_mode]}，端口 {self.config.port}。"

    def _clear_observation(self):
        self.initialized = None
        self.runtime_info = None
        self.health_ok = False
        self._setup_identity = None
        for name in ("_reply", "_setup_reply"):
            reply = getattr(self, name)
            setattr(self, name, None)
            if reply is not None:
                reply.abort()

    def apply_settings(self, settings, *, restart=False, exiting=False):
        if self.pending_start or self.state in {State.STARTING, State.STOPPING}:
            raise ConfigError("服务正在启动或停止，请完成后再保存设置。")
        network_changed = any(getattr(settings, key) != getattr(self.config, key)
                              for key in ("access_mode", "port", "lan_address", "remote_url"))
        requires_restart = network_changed and self.network_settings_changed(settings)
        if self.process is not None and requires_restart and not (restart or exiting):
            raise ConfigError("访问方式变更需要重启 SeedLab，请选择保存并重启。")
        self.config_store.save(settings)
        self.network_warning = "设置将在下次由控制中心启动时生效。" if self.state == State.EXTERNAL else ""
        self._event("运行设置已保存。" if not network_changed else "访问设置已保存：" + MODE_LABELS[settings.access_mode] + "。")
        if self.process is not None and requires_restart and restart:
            self.restart()
        elif self.process is None and network_changed and (self.state not in {State.EXTERNAL, State.OTHER}
                                                          or settings.port != self.external_port):
            self._clear_observation()
            self.external_port = self.confirmed_url = None
            self.start_config = None
            self._set_state(State.STOPPED, "访问设置已保存，请启动当前部署的 SeedLab。")
            if self.polling:
                self.poll_health()
        self.changed.emit()

    def network_settings_changed(self, settings):
        return any(getattr(settings, key) != getattr(self.active_config, key)
                   for key in ("access_mode", "port", "lan_address", "remote_url"))

    @property
    def label(self):
        return "正在重启" if self.restart_pending and self.state != State.ERROR else STATE_LABELS[self.state]

    @property
    def can_start(self):
        return (not self.maintenance and self.process is None and not self.pending_start
                and self.state in {State.STOPPED, State.ERROR})

    @property
    def can_stop(self):
        return self.process is not None and self.state in {State.RUNNING, State.ERROR}

    @property
    def can_open(self):
        return self.state in {State.RUNNING, State.EXTERNAL} and self.health_ok and bool(self.user_url)

    def _event(self, message):
        self.control_log.info("[事件] %s", message)
        self.event.emit(message)

    def _set_state(self, state, message):
        if state == State.ERROR and self.process is None:
            self.start_config = None
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
                probe.bind((self.bind_host, self.port))
            return True
        except OSError:
            return False

    def poll_health(self):
        if self._reply is not None:
            return
        request = QNetworkRequest(QUrl(self.url + "/api/health"))
        request.setRawHeader(b"X-SeedLab-Control", self.identity.probe_token.encode())
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setTransferTimeout(1200)
        self._reply = self.network.get(request)

    def _health_finished(self, reply):
        if reply is self._setup_reply:
            self._setup_reply = None
            try:
                payload = json.loads(bytes(reply.readAll())) if reply.error() == QNetworkReply.NetworkError.NoError else None
                self.initialized = (payload.get("initialized") if isinstance(payload, dict)
                    and self.state in {State.RUNNING, State.EXTERNAL} and self.runtime_info
                    and self._setup_identity == self.runtime_info else None)
            except (ValueError, UnicodeDecodeError):
                self.initialized = None
            reply.deleteLater()
            self.changed.emit()
            return
        if reply is not self._reply:
            reply.deleteLater()
            return
        self._reply = None
        if reply.request().url().toString() != self.url + "/api/health":
            reply.deleteLater()
            return
        try:
            payload = json.loads(bytes(reply.readAll())) if reply.error() == QNetworkReply.NetworkError.NoError else None
        except (ValueError, UnicodeDecodeError):
            payload = None
        reply.deleteLater()
        self.accept_health(payload)

    def accept_health(self, payload):
        seedlab = isinstance(payload, dict) and payload.get("status") == "ok" and payload.get("version") == VERSION
        matches = (seedlab and self.identity.matches(payload)
                   and type(payload.get("port")) is int and payload.get("port") == self.port
                   and type(payload.get("pid")) is int and payload["pid"] > 0
                   and payload.get("access_mode") in MODE_LABELS
                   and payload.get("bind_host") == ("0.0.0.0" if payload.get("access_mode") == "lan" else "127.0.0.1"))
        own_process = (matches and self.process is not None and payload.get("pid") == self.process.pid
                       and payload["access_mode"] == self.active_config.access_mode
                       and payload["bind_host"] == self.active_config.bind_host)
        healthy = bool(matches if self.process is None else own_process)
        was_healthy = self.health_ok
        self.health_ok = healthy
        self.runtime_info = {key: payload[key] for key in ("instance_id", "data_root", "port", "access_mode", "bind_host", "pid")} if matches and type(payload.get("pid")) is int else None
        if not healthy:
            self.initialized = None
            self._setup_identity = None
            if self._setup_reply is not None:
                self._setup_reply.abort()
        if self.process is None:
            if seedlab and not healthy:
                self.pending_start = False
                self.external_port = self.active_config.port
                self.confirmed_url = self.active_config.health_url
                self.start_config = None
                self._set_state(State.OTHER, "检测到另一份 SeedLab 正在运行。当前控制中心不接管该实例，"
                                "不会读取其账号状态；请修改访问端口，或在原入口停止该服务后重试。")
            elif healthy:
                self.pending_start = False
                if self.state != State.EXTERNAL:
                    self.external_port = self.active_config.port
                    self.confirmed_url = self.active_config.health_url
                    self.start_config = None
                    self._event("当前数据目录的 SeedLab 已由其他入口启动。")
                self._set_state(State.EXTERNAL, "已核对为当前数据目录；可打开网页，但停止和重启须在原入口操作。")
            elif self.pending_start:
                self.pending_start = False
                self._spawn()
            elif self.state in {State.EXTERNAL, State.OTHER} and self._port_free():
                self.external_port = self.confirmed_url = None
                self.initialized = None
                self._set_state(State.STOPPED, "外部服务已停止，可从此处启动。")
            elif not self._port_free():
                self._set_state(State.ERROR, f"端口 {self.port} 已被其他程序占用。请关闭占用程序后重试。")
        elif healthy and self.process.poll() is None and self.state not in {State.STOPPING, State.ERROR}:
            if self.state == State.STARTING:
                self.started_at = datetime.now()
                self.restart_pending = False
                self._event("SeedLab 启动成功：" + MODE_LABELS[self.active_config.access_mode] + "。")
                self.server_log.info("[事件] SeedLab 启动成功。")
            elif not was_healthy:
                self._event("健康检查已恢复。")
            self._set_state(State.RUNNING, "SeedLab 正常运行，可打开浏览器开始实验工作。")
        elif seedlab and not healthy and self.process is not None and self.state not in {State.STOPPING, State.ERROR}:
            self._set_state(State.ERROR, "当前端口返回的部署身份或运行方式与本次启动不一致。"
                            "当前服务未通过确认；请检查访问设置并停止本次启动后重试。")
        if healthy and self.state in {State.RUNNING, State.EXTERNAL} and self.polling and self._setup_reply is None:
            request = QNetworkRequest(QUrl(self.url + "/api/setup/status"))
            request.setTransferTimeout(1200)
            self._setup_identity = self.runtime_info.copy()
            self._setup_reply = self.network.get(request)
        self.changed.emit()

    def start(self):
        if not self.can_start:
            return
        self.start_config, self.network_warning = resolve_lan(self.config, lan_addresses())
        if self.start_config.access_mode == "lan" and not self.start_config.lan_address:
            self.start_config = None
            self._set_state(State.ERROR, "当前没有可用的局域网地址，请连接网络或改用仅本机使用。")
            return
        if not self.paths.launcher_available:
            self._set_state(State.ERROR, "运行文件缺失，请检查 SeedLab 程序目录或重新安装后再启动。")
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
            self._set_state(State.ERROR, f"端口 {self.port} 已被其他程序占用。请关闭占用程序后重试。")
            return
        try:
            self.stop_file = self.paths.new_stop_file()
            environment = os.environ.copy()
            environment.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", SEEDLAB_ENV="production")
            environment["SEEDLAB_COOKIE_SECURE"] = "true" if self.active_config.cookie_secure else "false"
            if self.paths.database is not None:
                environment["SEEDLAB_DATABASE_URL"] = "sqlite:///" + self.paths.database.resolve().as_posix()
            environment["SEEDLAB_BOOTSTRAP_TOKEN_PATH"] = str(self.paths.bootstrap_token)
            self.process = subprocess.Popen(self.paths.server_command(self.stop_file, self.active_config),
                cwd=self.paths.root, env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self.running_config = self.active_config
            self.start_config = None
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
                    if line.startswith("数据库启动未通过："):
                        self._output_error.emit(line.partition("：")[2].strip())
                    for marker, reason in (("数据库升级失败", "数据库升级失败，请查看日志并保留现有数据库。"),
                                           ("前端生产文件缺失", "前端生产文件缺失，请先构建前端。"),
                                           ("address already in use", f"端口 {self.port} 已被其他程序占用。")):
                        if marker in line:
                            self._output_error.emit(reason)
        except Exception:
            self.server_log.exception("服务日志读取失败")

    def _remember_error(self, reason):
        self._failure_reason = reason

    def stop(self):
        if self.process is None:
            self.pending_start = False
            self.start_config = None
            if self.state not in {State.EXTERNAL, State.OTHER}:
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
        self.initialized = None
        self._timeout_notified = False
        self._set_state(State.STOPPING, "正在完成当前请求并关闭服务，请稍候。")
        self._event("已请求正常停止 SeedLab。")

    def restart(self):
        if self.can_stop and not self.maintenance:
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
                self.running_config = None
                self._clear_observation()
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
