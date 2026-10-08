"""Production upgrade handoff and local administrator recovery, without business UI changes."""
from pathlib import Path
import subprocess
from uuid import uuid4

from PySide6.QtCore import QThreadPool, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QLineEdit, QMessageBox, QPushButton)

from app.core.auth import password_error
from app.services.admin_recovery import administrators, reset_administrator, schema_information
from app.version import VERSION
from control_center.operations import Job
from control_center.server_manager import State, STATE_LABELS
from control_center.widgets.status_card import Card, label
from production_ops import OperationsError
from production_ops.deployment import UPDATER
from production_ops.package import inspect_package


class UpgradePanel(Card):
    def __init__(self, window):
        super().__init__()
        self.window, self.manager = window, window.manager
        self.package = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.box.addWidget(label(f"当前版本：SeedLab v{VERSION}", "cardTitle"))
        self.health_label = label("", "muted", True)
        self.box.addWidget(self.health_label)
        self.manager.changed.connect(self.refresh_status)
        self.window.operations.changed.connect(self.refresh_status)
        self.refresh_status()
        self.details = label("选择本地升级包后，可检查目标版本与数据库兼容性。", "muted", True)
        self.box.addWidget(self.details)
        self.choose = QPushButton("选择升级包")
        self.choose.clicked.connect(self.choose_package)
        self.start = QPushButton("开始升级")
        self.start.setObjectName("primary")
        self.start.setEnabled(False)
        self.start.clicked.connect(self.start_upgrade)
        self.recovery = QPushButton("打开升级与恢复助手")
        self.recovery.clicked.connect(lambda: self.open_updater())
        for button in (self.choose, self.start, self.recovery):
            self.box.addWidget(button)
        if self.manager.paths.deployment_root is None:
            self.choose.setEnabled(False)
            self.recovery.setEnabled(False)
            self.details.setText("当前程序尚未接入统一升级入口。首次升级请双击 SeedLab 首次升级助手。")
        self.handoff_timer = QTimer(self)
        self.handoff_timer.setInterval(200)
        self.handoff_timer.timeout.connect(self.check_handoff)
        self.handoff_path = None

    def refresh_status(self):
        self.health_label.setText(f"服务状态：{STATE_LABELS[self.manager.state]}\n"
                                  f"数据库状态：{self.window.operations.database_status}")

    def choose_package(self):
        filename, _ = QFileDialog.getOpenFileName(self, "选择 SeedLab 升级包", "", "SeedLab 升级包 (*.zip)")
        if not filename:
            return
        self.start.setEnabled(False)
        self.choose.setEnabled(False)
        self.details.setText("正在检查升级包，当前版本可继续使用…")
        def inspect():
            manifest = inspect_package(Path(filename), VERSION)
            schema = schema_information(self.manager.paths.database, self.manager.paths.migration_root)
            if schema["current"] != manifest["target_alembic_revision"]:
                raise OperationsError("此升级需要调整数据库，本版助手暂不支持。请联系维护人员取得对应升级方案。")
            return manifest
        self.job = Job(inspect)
        self.job.signals.finished.connect(lambda result, error: self.checked(filename, result, error))
        self.pool.start(self.job)

    def checked(self, filename, manifest, error):
        self.choose.setEnabled(True)
        self.job = None
        if error:
            self.details.setText(str(error) if isinstance(error, OperationsError) else "升级包无法读取，请重新选择完整升级包。")
            return
        self.package = Path(filename)
        self.details.setText(f"当前版本：v{VERSION}\n目标版本：v{manifest['target_application_version']}\n"
                             "数据库无需调整。升级包检查通过，助手将继续检查数据库并准备新程序。\n实验数据目录保持不变。")
        self.start.setEnabled(True)

    def start_upgrade(self):
        self.open_updater(self.package)

    def open_updater(self, package=None):
        root = self.manager.paths.deployment_root
        if root is None:
            return
        executable = root / UPDATER
        if not executable.is_file():
            self.details.setText("独立升级助手缺失，请联系维护人员补齐程序；当前版本保持运行。")
            return
        command = [str(executable), "--root", str(root)]
        if package is not None:
            self.handoff_path = root / "Updates" / ("handoff-" + uuid4().hex + ".request")
            self.handoff_path.parent.mkdir(parents=True, exist_ok=True)
            command += ["--package", str(package), "--handoff", str(self.handoff_path)]
        try:
            subprocess.Popen(command, cwd=root, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            self.details.setText("升级助手未能打开，请检查程序目录或查看运行日志。")
            self.manager.control_log.exception("升级助手启动失败")
            return
        if package is not None:
            self.handoff_timer.start()
        self.details.setText("升级助手已打开。当前版本继续运行；在助手中确认升级后，本控制中心会正常退出。")

    def check_handoff(self):
        if self.handoff_path and self.handoff_path.is_file():
            if self.window.begin_upgrade_exit():
                self.handoff_timer.stop()
                self.handoff_path.unlink(missing_ok=True)


class AdminRecoveryPanel(Card):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.busy = False
        self.pending = None
        self.restart = False
        self.box.addWidget(label("管理员账户恢复", "cardTitle"))
        self.box.addWidget(label("忘记管理员密码时，可在这台电脑恢复已有管理员登录。操作会停止服务，不改变实验记录。", "muted", True))
        self.schema_label = label("数据库信息尚未读取。", "muted", True)
        self.box.addWidget(self.schema_label)
        self.admin = QComboBox()
        self.password = QLineEdit()
        self.confirm = QLineEdit()
        for field in (self.password, self.confirm):
            field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setMaxLength(128)
        self.password.setPlaceholderText("输入 8 至 128 位新密码")
        self.confirm.setPlaceholderText("再次输入新密码")
        form = QFormLayout()
        form.addRow("已有管理员", self.admin)
        form.addRow("新密码", self.password)
        form.addRow("确认密码", self.confirm)
        self.box.addLayout(form)
        self.reload = QPushButton("读取管理员与数据库信息")
        self.reload.clicked.connect(self.load)
        self.reset = QPushButton("重置管理员密码")
        self.reset.setEnabled(False)
        self.reset.clicked.connect(self.request_reset)
        self.box.addWidget(self.reload)
        self.box.addWidget(self.reset)
        self.message = label("只恢复所选管理员的登录，不创建账号。", "muted", True)
        self.box.addWidget(self.message)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.after_stop)

    def run(self, operation, completed):
        self.busy = True
        self.reload.setEnabled(False)
        self.reset.setEnabled(False)
        self.job = Job(operation)
        self.job.signals.finished.connect(lambda result, error: self.finished(result, error, completed))
        self.pool.start(self.job)

    def finished(self, result, error, completed):
        self.busy = False
        self.job = None
        self.reload.setEnabled(True)
        self.reset.setEnabled(self.admin.count() > 0)
        if error:
            # Never format credential operation arguments or exception locals into logs.
            self.manager.control_log.error("管理员维护未完成，错误类别：%s", type(error).__name__)
            self.message.setText(str(error) if isinstance(error, ValueError) else "维护操作未完成，请检查数据位置、程序版本或运行日志。")
        else:
            completed(result)
        if self.restart:
            self.restart = False
            self.manager.maintenance = False
            self.manager.start()
        elif self.pending is None:
            self.manager.maintenance = False

    def load(self):
        paths = self.manager.paths
        if paths.database is None or not paths.database.is_file():
            self.message.setText("尚未找到现有实验数据库，请先检查数据位置。")
            return
        self.run(lambda: (schema_information(paths.database, paths.migration_root), administrators(paths.database)), self.loaded)

    def loaded(self, result):
        schema, admins = result
        self.schema_label.setText(f"数据库结构版本：{schema['current'] or '尚未建立'}\n当前程序支持版本：{schema['target']}")
        self.admin.clear()
        for user in admins:
            text = f"{user['display_name']}（{user['username']}）" + (" · 已停用" if not user['active'] else "")
            self.admin.addItem(text, user["id"])
        self.reset.setEnabled(bool(admins))
        self.message.setText("请选择需要恢复登录的管理员。" if admins else "没有可恢复的已有管理员，请联系维护人员；不会新建账号。")

    def request_reset(self):
        password, confirmation = self.password.text(), self.confirm.text()
        if password != confirmation or password_error(password):
            self.message.setText("两次密码须一致，长度须为 8 至 128 位。")
            return
        if self.manager.state in {State.EXTERNAL, State.OTHER, State.STARTING, State.STOPPING}:
            self.message.setText("请先从原控制中心停止服务，并等待启停操作结束。")
            return
        if QMessageBox.question(self, "恢复管理员登录", "将重置所选管理员密码并使其已有登录失效。服务运行时会先正常停止，完成后重新启动。实验记录保持不变。") != QMessageBox.StandardButton.Yes:
            return
        self.pending = (self.admin.currentData(), password, confirmation)
        self.password.clear()
        self.confirm.clear()
        self.restart = self.manager.process is not None
        self.manager.maintenance = True
        self.busy = True
        self.reload.setEnabled(False)
        self.reset.setEnabled(False)
        if self.restart:
            self.manager.stop()
        self.timer.start()
        self.after_stop()

    def after_stop(self):
        if self.manager.process is not None or self.manager.pending_start:
            self.message.setText("正在等待 SeedLab 正常停止…")
            return
        self.timer.stop()
        values, self.pending = self.pending, None
        paths = self.manager.paths
        self.run(lambda: reset_administrator(paths.database, paths.migration_root, *values), self.reset_done)

    def reset_done(self, result):
        self.message.setText("管理员密码已重置，原登录已失效。请使用新密码登录。")
        self.manager.control_log.info("[事件] 管理员密码恢复完成，原登录已失效。")
