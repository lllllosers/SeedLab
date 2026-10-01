"""Editable deployment panels. Drafts survive navigation and health polling."""
from dataclasses import replace

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QButtonGroup, QRadioButton, QComboBox,
    QLineEdit, QPushButton, QCheckBox, QSpinBox, QAbstractSpinBox, QHBoxLayout, QMessageBox)

from ..config_store import ConfigError, normalize_remote_url
from ..network_service import MODE_LABELS, RemoteChecker, lan_addresses, resolve_lan
from ..server_manager import State
from .status_card import Card, label
from .action_row import ActionRow


def action(text, slot):
    item = QPushButton(text)
    item.clicked.connect(slot)
    return item


def copy_text(parent, text):
    if not text:
        return False
    try:
        QApplication.clipboard().setText(text)
    except Exception:
        QMessageBox.warning(parent, "复制未完成", "无法写入剪贴板，请手动选择并复制。")
        return False
    return True


class NetworkPanel(Card):
    save_requested = Signal(object)

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self._loading = True
        self._baseline = manager.config
        self.box.addWidget(label("访问方式", "cardTitle"))
        modes = QHBoxLayout()
        self.group = QButtonGroup(self)
        self.modes = {}
        for mode, title in MODE_LABELS.items():
            radio = QRadioButton(title)
            self.group.addButton(radio)
            modes.addWidget(radio)
            self.modes[mode] = radio
            radio.toggled.connect(self.draft_changed)
        self.box.addLayout(modes)
        ports = QHBoxLayout()
        ports.addWidget(label("访问端口", "fieldLabel"))
        self.port_edit = QSpinBox()
        self.port_edit.setRange(1, 65535)
        self.port_edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        ports.addWidget(self.port_edit)
        ports.addStretch()
        self.box.addLayout(ports)
        self.port_edit.valueChanged.connect(self.draft_changed)
        self.lan_label = label("选择当前网络地址", "fieldLabel")
        self.box.addWidget(self.lan_label)
        self.lan_combo = QComboBox()
        self.box.addWidget(self.lan_combo)
        self.lan_refresh = action("刷新网络地址", self.refresh_addresses)
        self.box.addWidget(self.lan_refresh)
        self.remote_label = label("远程 HTTPS 根地址", "fieldLabel")
        self.box.addWidget(self.remote_label)
        self.remote_edit = QLineEdit()
        self.remote_edit.setPlaceholderText("https://您的远程域名")
        self.box.addWidget(self.remote_edit)
        self.preview = label("", "value", True)
        self.box.addWidget(self.preview)
        self.warning_label = label("", "muted", True)
        self.box.addWidget(self.warning_label)
        self.notice = label("", "muted", True)
        self.box.addWidget(self.notice)
        self.dirty_label = label("", "muted")
        self.box.addWidget(self.dirty_label)
        self.save_button = action("保存访问设置", self.save)
        self.check_button = action("检测远程连接", self.check_remote)
        self.copy_button = action("复制访问地址", self.copy_address)
        self.open_button = action("打开 SeedLab", self.open_address)
        self.box.addWidget(ActionRow((self.save_button, self.check_button, self.copy_button, self.open_button)))
        self.remote_status = label("尚未检测远程入口", "muted", True)
        self.box.addWidget(self.remote_status)
        self.current = label("", "muted", True)
        self.box.addWidget(self.current)
        self.help = label("", "muted", True)
        self.box.addWidget(self.help)
        self.checker = RemoteChecker(manager.control_log, self)
        self.checker.changed.connect(self.refresh)
        self.checker.event.connect(manager._event)
        self.timer = QTimer(self)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self.auto_check)
        if manager.polling:
            self.timer.start()
        self._addresses = []
        self._loading = True
        self.lan_combo.currentIndexChanged.connect(self.draft_changed)
        self.remote_edit.textChanged.connect(self.draft_changed)
        self.load()

    @property
    def mode(self):
        return next((key for key, item in self.modes.items() if item.isChecked()), "local")

    def candidate(self):
        return replace(self.manager.config, access_mode=self.mode, port=self.port_edit.value(),
                       lan_address=self.lan_combo.currentData() if self.mode == "lan" else self.manager.config.lan_address,
                       remote_url=self.remote_edit.text().strip() or None)

    @property
    def dirty(self):
        try:
            value = self.candidate()
            return any(getattr(value, key) != getattr(self._baseline, key)
                       for key in ("access_mode", "port", "lan_address", "remote_url"))
        except ConfigError:
            return True

    def load(self):
        self._loading = True
        self._baseline = self.manager.config
        self.modes[self._baseline.access_mode].setChecked(True)
        self.port_edit.setValue(self._baseline.port)
        self.remote_edit.setText(self._baseline.remote_url or "")
        self.refresh_addresses()
        self._loading = False
        self.draft_changed()

    def refresh_addresses(self):
        previous = self.lan_combo.currentData() or self._baseline.lan_address
        self._addresses = lan_addresses()
        self.lan_combo.blockSignals(True)
        self.lan_combo.clear()
        for item in self._addresses:
            self.lan_combo.addItem(f"{item.name} · {item.address}" + ("（其他网络）" if item.other else ""), item.address)
        index = self.lan_combo.findData(previous)
        self.lan_combo.setCurrentIndex(index if index >= 0 else (0 if self._addresses else -1))
        self.lan_combo.blockSignals(False)
        self.draft_changed()

    def draft_changed(self, *_):
        if self._loading:
            return
        lan, remote = self.mode == "lan", self.mode == "remote"
        for item in (self.lan_label, self.lan_combo, self.lan_refresh):
            item.setVisible(lan)
        for item in (self.remote_label, self.remote_edit, self.check_button, self.remote_status):
            item.setVisible(remote)
        try:
            candidate = self.candidate()
            address = candidate.user_url or "当前没有可用的局域网地址"
        except ConfigError as error:
            address = str(error)
        self.preview.setText(address)
        self.dirty_label.setText("有未保存的设置" if self.dirty else "设置已保存")
        self.help.setText({"local": "仅限这台电脑访问。",
            "lan": "同一局域网设备可使用上述地址。若无法连接，请检查网络及 Windows 防火墙；控制中心不会更改防火墙。",
            "remote": "请先在独立的 SakuraFrp 客户端配置隧道，映射到本机端口。控制中心只保存地址和检测连接，不管理隧道或账号。"}[self.mode])
        if self.checker.url and self.checker.url != self.remote_edit.text().strip().rstrip("/"):
            self.checker.reset()
        self.refresh()

    def save(self):
        try:
            candidate = self.candidate()
            if candidate.access_mode == "lan" and candidate.lan_address not in {item.address for item in self._addresses}:
                raise ConfigError("当前没有可用的局域网地址，请连接网络后刷新。")
            self.save_requested.emit(candidate)
        except ConfigError as error:
            QMessageBox.warning(self, "请检查访问设置", str(error))

    def check_remote(self):
        try:
            self.checker.check(normalize_remote_url(self.remote_edit.text()))
        except ConfigError as error:
            QMessageBox.warning(self, "请检查远程地址", str(error))

    def auto_check(self):
        if self.manager.state not in {State.EXTERNAL, State.OTHER} and self.manager.can_open and self.manager.active_config.access_mode == "remote":
            self.checker.check(self.manager.user_url, manual=False)

    def copy_address(self):
        try:
            if copy_text(self, self.candidate().user_url):
                self.notice.setText("访问地址已复制。")
        except ConfigError as error:
            self.notice.setText(str(error))

    def open_address(self):
        if self.manager.can_open:
            QDesktopServices.openUrl(QUrl(self.manager.user_url))

    def refresh(self):
        manager = self.manager
        self.remote_status.setText(self.checker.message)
        self.check_button.setEnabled(self.checker.reply is None)
        self.open_button.setEnabled(manager.can_open)
        self.current.setText(("检测到另一份 SeedLab；当前控制中心不接管，也不读取其账号状态。\n"
            if manager.state == State.OTHER else
            f"{'当前运行方式' if manager.process or manager.state == State.EXTERNAL else '下次启动方式'}：{manager.mode_label}\n"
            f"访问地址：{manager.user_url or '尚未配置'}\n") + manager.configuration_status)
        _, warning = resolve_lan(self._baseline, self._addresses)
        message = manager.config_store.warning or manager.network_warning or (warning if self.mode == "lan" else "")
        self.warning_label.setText(message)
        self.warning_label.setVisible(bool(message))


class SettingsPanel(Card):
    save_requested = Signal(object)

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.box.addWidget(label("运行设置", "cardTitle"))
        self.mode_label = label("", "muted", True)
        self.box.addWidget(self.mode_label)
        self.warning = label("", "muted", True)
        self.box.addWidget(self.warning)
        self.enabled = QCheckBox("启用每日自动备份")
        self.box.addWidget(self.enabled)
        row = QHBoxLayout()
        row.addWidget(label("保留最近的自动备份", "fieldLabel"))
        self.retention = QSpinBox()
        self.retention.setRange(1, 90)
        self.retention.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.retention.setSuffix(" 份")
        row.addWidget(self.retention)
        row.addStretch()
        self.box.addLayout(row)
        self.auto_start = QCheckBox("启动控制中心后自动启动 SeedLab")
        self.box.addWidget(self.auto_start)
        self.dirty_label = label("", "muted")
        self.box.addWidget(self.dirty_label)
        self.save_button = action("保存运行设置", lambda: self.save_requested.emit(self.candidate()))
        self.box.addWidget(ActionRow((self.save_button,)))
        self.enabled.toggled.connect(self.refresh)
        self.retention.valueChanged.connect(self.refresh)
        self.auto_start.toggled.connect(self.refresh)
        self.load()

    def candidate(self):
        return replace(self.manager.config, auto_backup_enabled=self.enabled.isChecked(),
                       auto_backup_retention=self.retention.value(), auto_start_server=self.auto_start.isChecked())

    @property
    def dirty(self):
        return (self.enabled.isChecked(), self.retention.value(), self.auto_start.isChecked()) != self._baseline

    def load(self):
        config = self.manager.config
        self._baseline = config.auto_backup_enabled, config.auto_backup_retention, config.auto_start_server
        self.enabled.setChecked(config.auto_backup_enabled)
        self.retention.setValue(config.auto_backup_retention)
        self.auto_start.setChecked(config.auto_start_server)
        self.refresh()

    def refresh(self, *_):
        self.warning.setText(self.manager.config_store.warning)
        self.warning.setVisible(bool(self.manager.config_store.warning))
        self.mode_label.setText(f"已保存访问方式：{MODE_LABELS[self.manager.config.access_mode]}\n访问端口：{self.manager.config.port}（可在网络访问页修改）")
        self.dirty_label.setText("有未保存的设置" if self.dirty else "设置已保存")


class BackupPanel(Card):
    def __init__(self, manager, operations):
        super().__init__()
        self.manager, self.operations = manager, operations
        self.box.addWidget(label("当前数据库", "cardTitle"))
        self.database_details = label("", None, True)
        self.box.addWidget(self.database_details)
        self.database_path = QLineEdit()
        self.database_path.setReadOnly(True)
        self.box.addWidget(self.database_path)
        self.health = label("尚未检查", "muted", True)
        self.box.addWidget(self.health)
        self.check_button = action("立即检查", operations.check)
        self.box.addWidget(ActionRow((self.check_button,)))
        self.box.addWidget(label("自动备份", "cardTitle"))
        self.auto_status = label("", None, True)
        self.box.addWidget(self.auto_status)
        self.box.addWidget(ActionRow((action("打开备份目录", self.open_backups),)))
        self.box.addWidget(label("手工备份", "cardTitle"))
        self.box.addWidget(label("需要时随时创建独立备份；手工备份不会自动删除。", "muted", True))
        self.manual_status = label("尚无手工备份", None, True)
        self.box.addWidget(self.manual_status)
        self.backup_button = action("立即备份", operations.manual)
        self.box.addWidget(ActionRow((self.backup_button,)))
        self.error = label("", "muted", True)
        self.box.addWidget(self.error)
        operations.changed.connect(self.refresh)
        self.refresh()

    def open_backups(self):
        # Opening a directory does not create it or touch historical snapshots.
        if self.manager.paths.backups.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.manager.paths.backups)))
        else:
            self.error.setText("首次备份后会建立备份目录。")

    @staticmethod
    def describe(path):
        if not path:
            return "尚无备份"
        try:
            return f"{path.name}\n{path.stat().st_size / 1024 ** 2:.2f} MB"
        except OSError:
            return "备份文件暂时无法读取，请打开目录检查。"

    def refresh(self):
        manager, operations = self.manager, self.operations
        name, path, size = manager.paths.database_info()
        self.database_details.setText(f"文件名：{name}\n文件大小：{size}")
        self.database_path.setText(path)
        self.health.setText("正在检查…" if operations.busy and operations.kind == "check" else "数据库状态：" + operations.database_status)
        self.auto_status.setText(("已启用：每天首次成功运行时备份" if manager.config.auto_backup_enabled else "自动备份已关闭")
            + f"\n保留最近 {manager.config.auto_backup_retention} 份有效备份\n最近自动备份：" + self.describe(operations.latest["auto"])
            + ("\n当前服务由其他入口启动，自动备份将在由控制中心启动时执行。" if manager.state == State.EXTERNAL else ""))
        self.manual_status.setText("最近手工备份：" + self.describe(operations.latest["manual"]))
        self.backup_button.setText("正在备份…" if operations.busy and operations.kind in {"manual", "auto"} else "立即备份")
        for item in (self.check_button, self.backup_button):
            item.setEnabled(not operations.busy and manager.paths.database is not None)
        self.error.setText(operations.error)
