"""Five-step deployment setup. Database work runs outside the GUI thread."""
from dataclasses import replace
import logging
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QLineEdit, QFileDialog, QPushButton, QScrollArea)
from PySide6.QtCore import Qt

from .config_store import ConfigError, DeploymentSettings
from .installation import InstallationError, inspect_data_root, initialize_data_root, suggested_data_root
from .network_service import MODE_LABELS
from .operations import Job
from .server_manager import State
from .theme import QSS, window_dimensions
from .widgets.status_card import Card, label
from .widgets.operations_panels import NetworkPanel, SettingsPanel
from .brand import product_icon
from . import installation as deployment


class WizardDraft(QObject):
    state = State.STOPPED
    polling = False
    can_open = False
    process = None
    pending_start = False
    network_warning = ""

    def __init__(self):
        super().__init__()
        self.config = DeploymentSettings()
        self.config_store = SimpleNamespace(warning="")
        self.control_log = logging.getLogger("seedlab.first-run")

    @property
    def active_config(self):
        return self.config

    @property
    def user_url(self):
        return self.config.user_url

    @property
    def mode_label(self):
        return MODE_LABELS[self.config.access_mode]

    @property
    def configuration_status(self):
        return "请确认访问方式和端口。"

    def _event(self, message):
        self.control_log.info(message)


class FirstRunWizard(QWidget):
    completed = Signal(object)
    progress = Signal(str)

    def __init__(self, paths, installation):
        super().__init__()
        self.base_paths, self.installation = paths, installation
        self.paths = None
        self.inspection = None
        self.reuse = False
        self.busy = False
        self._completed = False
        self._job = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.draft = WizardDraft()
        self.setWindowTitle("SeedLab · 首次部署")
        self.setWindowIcon(product_icon())
        self.setObjectName("page")
        self.setStyleSheet(QSS)
        area = QApplication.primaryScreen().availableGeometry()
        target, minimum = window_dimensions(area.width(), area.height())
        self.resize(*target)
        self.setMinimumSize(*minimum)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)
        outer.addWidget(label("SeedLab", "brand"))
        self.steps = label("1 欢迎  ·  2 数据位置  ·  3 访问方式  ·  4 自动备份  ·  5 确认初始化", "muted", True)
        outer.addWidget(self.steps)
        if installation.warning:
            outer.addWidget(label(installation.warning, "muted", True))
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        welcome = self.page("欢迎使用 SeedLab", "首次使用需要准备数据目录和基本运行设置。以后实验数据、备份和日志都会保存在所选数据目录中。")
        welcome.addWidget(label("✓ 实验数据库\n✓ 自动备份\n✓ 运行设置\n✓ 日志", None, True))
        data = self.page("数据保存位置", "请选择独立、长期保存实验数据的位置。已有数据须先检查，系统不会覆盖其他文件。")
        self.root_edit = QLineEdit(str(suggested_data_root(paths.program_root)))
        data.addWidget(self.root_edit)
        select = QPushButton("选择位置")
        select.clicked.connect(self.choose_root)
        data.addWidget(select)
        self.data_message = label("建议使用程序目录同级的 SeedLabData；无法写入时可选择本机应用数据目录。", "muted", True)
        data.addWidget(self.data_message)
        self.reuse_button = QPushButton("使用现有数据")
        self.reuse_button.clicked.connect(self.use_existing)
        self.reuse_button.hide()
        data.addWidget(self.reuse_button)
        self.root_edit.textChanged.connect(self.reset_inspection)
        access = self.page("访问方式", "首次部署推荐仅本机使用或局域网共享。远程访问需要您自行准备 HTTPS 隧道。")
        self.network_panel = NetworkPanel(self.draft)
        for item in (self.network_panel.save_button, self.network_panel.dirty_label, self.network_panel.current):
            item.hide()
        access.addWidget(self.network_panel)
        backups = self.page("自动备份", "每天第一次由控制中心成功启动 SeedLab 时创建备份；手工备份不会自动删除。")
        self.settings_panel = SettingsPanel(self.draft)
        for item in (self.settings_panel.save_button, self.settings_panel.dirty_label, self.settings_panel.mode_label,
                     self.settings_panel.auto_start):
            item.hide()
        backups.addWidget(self.settings_panel)
        summary = self.page("确认并初始化", "请核对以下设置。初始化完成后会进入控制中心并启动 SeedLab，随后在网页设置首位管理员。")
        self.summary = label("", None, True)
        summary.addWidget(self.summary)
        self.progress_label = label("", "muted", True)
        self.progress.connect(self.progress_label.setText)
        outer.addWidget(self.progress_label)
        self.error_label = label("", "muted", True)
        outer.addWidget(self.error_label)
        actions = QHBoxLayout()
        self.back_button = QPushButton("上一步")
        self.back_button.clicked.connect(self.back)
        actions.addWidget(self.back_button)
        actions.addStretch()
        self.next_button = QPushButton("开始设置")
        self.next_button.setObjectName("primary")
        self.next_button.clicked.connect(self.next)
        actions.addWidget(self.next_button)
        outer.addLayout(actions)
        self.refresh()

    def page(self, title, instruction):
        content = QWidget()
        box = QVBoxLayout(content)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(label(title, "title"))
        box.addWidget(label(instruction, "muted", True))
        card = Card()
        box.addWidget(card)
        box.addStretch()
        content.setObjectName("page")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        self.pages.addWidget(scroll)
        return card.box

    def reset_inspection(self):
        self.inspection = None
        self.reuse = False
        self.reuse_button.hide()
        self.network_panel.setEnabled(True)
        self.settings_panel.setEnabled(True)

    def choose_root(self):
        path = QFileDialog.getExistingDirectory(self, "选择数据保存位置", self.root_edit.text())
        if path:
            self.root_edit.setText(path)

    def settings(self):
        network = self.network_panel.candidate()
        if network.access_mode == "lan" and not network.lan_address:
            raise ConfigError("当前没有可用的局域网地址，请连接网络或选择仅本机使用。")
        return replace(network, auto_backup_enabled=self.settings_panel.enabled.isChecked(),
                       auto_backup_retention=self.settings_panel.retention.value())

    def refresh(self):
        index = self.pages.currentIndex()
        self.steps.setText(f"第 {index + 1} / 5 步  ·  " + ("欢迎", "数据保存位置", "访问方式", "自动备份", "确认并初始化")[index])
        self.back_button.setEnabled(index > 0 and not self.busy)
        self.next_button.setEnabled(not self.busy)
        self.root_edit.setEnabled(not self.busy)
        self.reuse_button.setEnabled(not self.busy)
        self.next_button.setText("正在初始化…" if self.busy and index == 4 else "正在检查…" if self.busy else
                                 "开始设置" if index == 0 else "完成初始化" if index == 4 else "下一步")

    def back(self):
        if not self.busy:
            self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1))
            self.error_label.clear()
            self.refresh()

    def next(self):
        if self.busy:
            return
        self.error_label.clear()
        index = self.pages.currentIndex()
        try:
            if index == 1:
                raw = self.root_edit.text()
                if not raw.strip() or not Path(raw).is_absolute():
                    raise InstallationError("请选择完整的数据保存位置。")
                self.paths = replace(self.base_paths, data_root=Path(raw))
                self.begin("inspect", lambda: inspect_data_root(self.paths, allow_temporary=self.installation.allow_temporary))
                return
            if index == 2:
                deployment.ensure_port_available(self.settings())
            if index == 3:
                settings = self.settings()
                self.summary.setText(f"数据目录：{self.paths.data_root}\n访问方式：{MODE_LABELS[settings.access_mode]}\n"
                    f"访问地址：{settings.user_url}\n数据库位置：{self.paths.database}\n"
                    f"自动备份：{'启用' if settings.auto_backup_enabled else '关闭'}\n保留份数：{settings.auto_backup_retention} 份"
                    + ("\n使用现有数据库及运行设置，不覆盖原配置。" if self.reuse else "\n建立正式空库；原开发数据不会被移动或复制。"))
            if index == 4:
                settings = self.settings()
                self.begin("initialize", lambda: initialize_data_root(self.paths, settings, self.installation,
                    reuse=self.reuse, progress=self.progress.emit))
                return
            self.pages.setCurrentIndex(index + 1)
            self.refresh()
        except (InstallationError, ConfigError) as error:
            self.error_label.setText(str(error))

    def begin(self, kind, operation):
        self.busy = True
        self.kind = kind
        self._job = Job(operation)
        self._job.signals.finished.connect(self.finished)
        self.pool.start(self._job)
        self.refresh()

    def finished(self, result, error):
        self.busy = False
        self._job = None
        self.refresh()
        if error is not None:
            logging.getLogger("seedlab.first-run").error("首次部署步骤失败：%s", self.kind,
                exc_info=(type(error), error, error.__traceback__))
            self.error_label.setText(str(error) if isinstance(error, (InstallationError, ConfigError)) else
                "部署未完成，请检查写入权限、数据库和程序文件后重试。现有文件已保留，部署位置未更新。")
            return
        if self.kind == "inspect":
            self.inspection = result
            if result.existing:
                self.data_message.setText("发现已有 SeedLab 数据目录。数据库、运行设置和版本检查通过；使用后会保留原配置与账号。")
                self.reuse_button.show()
            else:
                self.pages.setCurrentIndex(2)
        else:
            self._completed = True
            self.completed.emit(result)
            self.close()
        self.refresh()

    def use_existing(self):
        if self.busy or not self.inspection or not self.inspection.existing:
            return
        self.reuse = True
        self.draft.config = self.inspection.settings
        self.network_panel.load()
        self.settings_panel.load()
        self.network_panel.setEnabled(False)
        self.settings_panel.setEnabled(False)
        self.pages.setCurrentIndex(2)
        self.refresh()

    def closeEvent(self, event):
        if self.busy:
            self.progress_label.setText("正在完成数据准备，请等待完成后再退出。")
            event.ignore()
        else:
            self.network_panel.checker.stop()
            if not self._completed:
                QApplication.instance().quit()
            event.accept()
