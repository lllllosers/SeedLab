"""GUI shell around the same offline executor used by the Bootstrap assistant."""
import argparse
from pathlib import Path
import sys

from PySide6.QtCore import QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QMessageBox, QFormLayout)

from app.services.database_upgrade import UpgradeError
from control_center.brand import product_icon
from control_center.operations import Job
from control_center.theme import QSS
from . import OperationsError
from .bootstrap import discover, inspect_legacy, adopt
from .deployment import DeploymentStore
from .executor import UpgradeExecutor
from .runtime import CandidateRuntime
from .windows import create_shortcut, connect_startup


class UpgradeWindow(QWidget):
    progress = Signal(str)

    def __init__(self, *, root=None, package=None, bootstrap=False, resources=None, handoff=None, isolated=False):
        super().__init__()
        self.bootstrap, self.resources, self.handoff, self.isolated = bootstrap, resources, handoff, isolated
        self.executor = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.busy = False
        self.setObjectName("page")
        self.setWindowTitle("SeedLab 首次升级助手" if bootstrap else "SeedLab 系统升级")
        self.setWindowIcon(product_icon())
        self.setStyleSheet(QSS)
        self.resize(690, 570)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        title = QLabel("升级 SeedLab")
        title.setObjectName("title")
        layout.addWidget(title)
        instruction = QLabel("先检查升级包。升级时会短暂停止 SeedLab，并为实验数据建立升级前备份。")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        form = QFormLayout()
        self.input_controls = []
        self.legacy = QLineEdit()
        self.legacy.setReadOnly(True)
        if bootstrap:
            row = QHBoxLayout()
            row.addWidget(self.legacy)
            choose = QPushButton("选择原 SeedLab 程序")
            choose.clicked.connect(self.choose_legacy)
            self.input_controls.append(choose)
            row.addWidget(choose)
            form.addRow("原程序", row)
        self.root = QLineEdit(str(root or ""))
        self.root.setReadOnly(not bootstrap)
        self.input_controls.append(self.root)
        form.addRow("程序保存位置", self.root)
        self.package = QLineEdit(str(package or ""))
        self.package.setReadOnly(True)
        row = QHBoxLayout()
        row.addWidget(self.package)
        choose_package = QPushButton("选择升级包")
        choose_package.clicked.connect(self.choose_package)
        self.input_controls.append(choose_package)
        row.addWidget(choose_package)
        form.addRow("升级包", row)
        self.details = QLabel("选择程序及升级包后，可开始检查。")
        self.details.setWordWrap(True)
        layout.addLayout(form)
        layout.addWidget(self.details)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress.connect(self.status.setText)
        layout.addStretch()
        actions = QHBoxLayout()
        self.prepare_button = QPushButton("检查并准备升级")
        self.prepare_button.clicked.connect(self.prepare)
        self.start_button = QPushButton("开始升级")
        self.start_button.setObjectName("primary")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self.start)
        self.restore_button = QPushButton("恢复上一版本")
        self.restore_button.setEnabled(False)
        self.restore_button.clicked.connect(self.restore)
        for button in (self.prepare_button, self.start_button, self.restore_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.logs_button = QPushButton("打开升级日志")
        self.logs_button.clicked.connect(self.open_logs)
        layout.addWidget(self.logs_button)
        if bootstrap:
            try:
                candidates = discover()
                if len(candidates) == 1:
                    self.set_legacy(candidates[0])
            except (OperationsError, OSError):
                self.status.setText("未能自动定位原程序，请选择原 SeedLab Control Center.exe。")
        elif root:
            self.attach_executor(Path(root))
            self.refresh_state()

    def attach_executor(self, root):
        store = DeploymentStore(root)
        self.executor = UpgradeExecutor(root, runtime=CandidateRuntime(store, isolated=self.isolated), progress=self.progress.emit)

    def choose_legacy(self):
        file, _ = QFileDialog.getOpenFileName(self, "选择原 SeedLab 程序", "", "SeedLab Control Center (SeedLab Control Center.exe)")
        if file:
            self.set_legacy(Path(file))

    def set_legacy(self, path):
        self.legacy.setText(str(path))
        self.run_job(lambda: inspect_legacy(path), self.legacy_ready)

    def legacy_ready(self, result):
        slot, data, root = result
        self.root.setText(str(root))
        self.details.setText(f"当前版本：v{slot['version']}\n实验数据：{data}\n数据库检查正常，数据目录保持不变。")

    def choose_package(self):
        file, _ = QFileDialog.getOpenFileName(self, "选择 SeedLab 升级包", "", "SeedLab 升级包 (*.zip)")
        if file:
            self.package.setText(file)

    def run_job(self, operation, success):
        if self.busy:
            return
        self.busy = True
        for control in self.input_controls:
            control.setEnabled(False)
        for button in (self.prepare_button, self.start_button, self.restore_button):
            button.setEnabled(False)
        self.job = Job(operation)
        self.job.signals.finished.connect(lambda result, error: self.finished(result, error, success))
        self.pool.start(self.job)

    def finished(self, result, error, success):
        self.busy = False
        for control in self.input_controls:
            control.setEnabled(True)
        self.job = None
        self.prepare_button.setEnabled(True)
        if error is not None:
            if self.executor:
                self.executor.log.error("操作未完成", exc_info=(type(error), error, error.__traceback__))
            message = str(error) if isinstance(error, (OperationsError, UpgradeError)) else "操作未完成，请保留原程序和实验数据，检查升级日志。"
            self.refresh_state()
            self.status.setText(message)
        else:
            success(result)

    def prepare(self):
        if not self.package.text() or not self.root.text():
            self.status.setText("请先选择原程序位置及完整升级包。")
            return
        root, package, legacy = Path(self.root.text()), Path(self.package.text()), Path(self.legacy.text())
        def prepare():
            if self.bootstrap:
                adopt(legacy, root, self.resources / "tools")
            self.attach_executor(root)
            return self.executor.stage(package)
        self.run_job(prepare, lambda state: self.refresh_state())

    def refresh_state(self):
        if not self.executor:
            return
        try:
            state = self.executor.store.load()
            pending = state["pending"]
            text = f"当前版本：v{state['current']['version']}\n实验数据：{state['data_root']}\n数据目录保持不变。"
            if pending:
                text += f"\n目标版本：v{pending['target']['version']}\n数据库无需调整。"
                self.status.setText("升级包已准备好。" if pending["phase"] == "staged" else
                                    "检测到上一次升级未完成。原程序和实验数据仍然保留，请先恢复原版本入口。")
            self.details.setText(text)
            self.prepare_button.setEnabled(not pending and not self.busy)
            self.start_button.setEnabled(bool(pending and pending["phase"] == "staged") and not self.busy)
            from .database import inspect
            previous = state["current"] if pending else state["previous"]
            valid = False
            if previous and (Path(previous["program_root"]) / "SeedLab Control Center.exe").is_file():
                try:
                    inspect(state["data_root"], Path(previous["program_root"]) / "app/migrations", previous["revision"])
                    valid = True
                except Exception:
                    pass
            self.restore_button.setEnabled(valid and not self.busy)
        except (OperationsError, OSError):
            self.status.setText("部署记录无法读取，请保留原文件并联系维护人员。")

    def start(self):
        message = "升级将短暂停止 SeedLab，数据目录保持不变。请确认当前实验录入已经保存。"
        if self.bootstrap:
            message += "\n请先在原控制中心选择“停止 SeedLab 并退出”。关闭窗口只会隐藏到托盘。"
        if QMessageBox.question(self, "开始升级", message) != QMessageBox.StandardButton.Yes:
            return
        self.run_job(lambda: self.executor.activate(handoff=self.handoff), self.completed)

    def completed(self, state):
        self.refresh_state()
        message = f"SeedLab v{state['current']['version']} 升级完成。实验数据目录保持不变。"
        if self.bootstrap and not self.isolated:
            try:
                connect_startup(self.executor.store.root, state["previous"]["program_root"])
                create_shortcut(self.executor.store.root, state["previous"]["program_root"])
            except (OSError, OperationsError) as error:
                self.executor.log.exception("启动入口接续未完成")
                message += "\n" + (str(error) if isinstance(error, OperationsError) else "启动入口未能接续，请直接打开程序根目录中的 SeedLab Launcher。")
        self.status.setText(message)

    def restore(self):
        if QMessageBox.question(self, "恢复上一版本", "请先停止 SeedLab 并退出控制中心。本次仅恢复程序入口，保留当前实验数据，不恢复旧数据库备份。") != QMessageBox.StandardButton.Yes:
            return
        self.run_job(self.executor.rollback, lambda state: (self.refresh_state(), self.status.setText("原版本入口已恢复，实验数据保持原样。")))

    def open_logs(self):
        if self.executor:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.executor.store.root / "Logs")))

    def closeEvent(self, event):
        if self.busy:
            self.status.setText("正在完成当前操作，请等待结束后关闭升级助手。")
            event.ignore()
        else:
            event.accept()


def main(arguments=None, *, bootstrap=False):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--isolated", action="store_true")
    args = parser.parse_args(arguments)
    resources = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1] / "dist/operations-v060"))
    root = args.root or (None if bootstrap else Path(sys.executable).parent)
    package = args.package or (resources / "SeedLab-v0.6.0-upgrade.zip" if bootstrap else None)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    window = UpgradeWindow(root=root, package=package, bootstrap=bootstrap, resources=resources,
                           handoff=args.handoff, isolated=args.isolated)
    window.show()
    return app.exec()
