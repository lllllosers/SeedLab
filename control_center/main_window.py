from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QStackedWidget, QScrollArea, QLineEdit, QPlainTextEdit,
    QSystemTrayIcon, QMenu, QMessageBox, QSizePolicy)

from app.version import VERSION
from .server_manager import ServerProcessManager, State
from .theme import QSS, window_dimensions
from .log_utils import user_log_tail, format_event
from .widgets.status_card import Card, StatusCard, StatusCardRow, label
from .widgets.nav_button import NavButton
from .widgets.info_grid import InfoGrid
from .widgets.action_row import ActionRow
from .operations import Operations
from .config_store import ConfigError
from .network_service import MODE_LABELS
from .widgets.operations_panels import NetworkPanel, BackupPanel, SettingsPanel, copy_text


NAVIGATION = ("概览", "运行管理", "网络访问", "数据与备份", "日志与诊断", "设置与关于")
NAV_ICONS = ("nav-overview", "nav-power", "nav-network", "nav-database", "nav-log", "nav-settings")


def button(text, slot, primary=False):
    item = QPushButton(text)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        item.setObjectName("primary")
    item.clicked.connect(slot)
    return item


class MainWindow(QMainWindow):
    def __init__(self, manager: ServerProcessManager | None = None):
        super().__init__()
        self.manager = manager or ServerProcessManager(parent=self)
        self.operations = Operations(self.manager, parent=self)
        self._allow_exit = False
        self._exit_after_stop = False
        self._hidden_notice = False
        self._token_revealed = False
        self.icon = QIcon(str(Path(__file__).parent / "assets/seedlab.svg"))
        self.setWindowIcon(self.icon)
        self.setWindowTitle("SeedLab 运行控制中心")
        self.setStyleSheet(QSS)
        area = QApplication.primaryScreen().availableGeometry()
        target, minimum = window_dimensions(area.width(), area.height())
        self.setMinimumSize(*minimum)
        self.resize(*target)
        self.move(area.center() - self.rect().center())

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(80)
        top = QHBoxLayout(header)
        top.setContentsMargins(26, 10, 28, 10)
        logo = QLabel()
        logo.setPixmap(self.icon.pixmap(42, 42))
        top.addWidget(logo)
        branding = QVBoxLayout()
        branding.setSpacing(3)
        branding.addWidget(label("SeedLab", "brand"))
        subtitle = label("种子试验管理系统 · 运行控制中心", "muted", True)
        subtitle.setMinimumHeight(30)
        branding.addWidget(subtitle)
        top.addLayout(branding, 1)
        top.addWidget(label(f"v{VERSION}", "muted"))
        top.addSpacing(16)
        self.header_state = label("● 已停止", "state")
        self.header_state.setMaximumHeight(30)
        top.addWidget(self.header_state, alignment=Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(header)
        body = QHBoxLayout()
        body.setSpacing(0)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        navigation = QVBoxLayout(sidebar)
        navigation.setContentsMargins(14, 24, 14, 22)
        navigation.setSpacing(7)
        self.nav_buttons = []
        for index, text in enumerate(NAVIGATION):
            nav = NavButton(text, NAV_ICONS[index], lambda checked=False, i=index: self.select_page(i))
            self.nav_buttons.append(nav)
            navigation.addWidget(nav)
        navigation.addStretch()
        navigation.addWidget(label("实验数据留在此设备\n按需选择访问方式", "muted", True))
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setObjectName("navScroll")
        sidebar_scroll.setFixedWidth(202)
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sidebar_scroll.setWidget(sidebar)
        body.addWidget(sidebar_scroll)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(central)
        self._build_overview()
        self._build_management()
        self._build_network()
        self._build_data()
        self._build_logs()
        self._build_about()
        self._build_tray()
        self.manager.changed.connect(self.refresh)
        self.operations.changed.connect(self.refresh)
        self.manager.event.connect(self.add_event)
        self.manager.stop_timed_out.connect(self.stop_timeout_dialog)
        self.events = []
        self.select_page(0)
        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(1000)
        self.ui_timer.timeout.connect(self.refresh)
        self.ui_timer.start()
        self.refresh()

    def _page(self, title, instruction):
        content = QWidget()
        content.setObjectName("page")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)
        layout.addWidget(label(title, "title"))
        layout.addWidget(label(instruction, "muted", True))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        self.pages.addWidget(scroll)
        return layout

    def _build_overview(self):
        page = self._page("概览", "在这里启动 SeedLab、查看运行状态，然后打开浏览器开始实验工作。")
        hero = Card()
        heading = QHBoxLayout()
        heading.addWidget(label("SeedLab 服务", "cardTitle"))
        heading.addStretch()
        self.hero_state = label("● 已停止", "state", True)
        heading.addWidget(self.hero_state)
        hero.box.addLayout(heading)
        self.hero_message = label("服务尚未启动", None, True)
        hero.box.addWidget(self.hero_message)
        self.hero_details = label("", "muted", True)
        hero.box.addWidget(self.hero_details)
        self.overview_primary = button("启动 SeedLab", self.overview_action, True)
        self.overview_restart = button("重启 SeedLab", self.manager.restart)
        self.error_logs = button("查看日志", lambda: self.select_page(4))
        hero.box.addWidget(ActionRow((self.overview_primary, self.overview_restart, self.error_logs)))
        page.addWidget(hero)
        self.bootstrap = Card()
        self.bootstrap.box.addWidget(label("首次管理员尚未设置", "cardTitle"))
        self.bootstrap_hint = label("使用本机初始化码设置首位管理员；完成后此提示会自动消失。", "muted", True)
        self.bootstrap.box.addWidget(self.bootstrap_hint)
        token_row = QHBoxLayout()
        self.token_edit = QLineEdit()
        self.token_edit.setReadOnly(True)
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setMaximumWidth(360)
        token_row.addWidget(self.token_edit, 1)
        token_row.addStretch()
        self.bootstrap.box.addLayout(token_row)
        self.reveal_button = button("显示初始化码", self.toggle_token)
        self.copy_button = button("复制初始化码", self.copy_token)
        self.setup_button = button("打开初始化页面", lambda: self.open_browser("/setup"), True)
        self.bootstrap.box.addWidget(ActionRow((self.reveal_button, self.copy_button, self.setup_button)))
        page.addWidget(self.bootstrap)
        self.service_card = StatusCard("服务状态", "已停止", "等待启动")
        self.access_card = StatusCard("当前访问", "仅本机使用", self.manager.url)
        self.database_card = StatusCard("数据库")
        page.addWidget(StatusCardRow((self.service_card, self.access_card, self.database_card)))
        recent = Card()
        recent.box.addWidget(label("最近事件", "cardTitle"))
        self.recent_events = label("最近没有需要处理的问题。", "muted", True)
        recent.box.addWidget(self.recent_events)
        page.addWidget(recent)
        page.addStretch()

    def _build_management(self):
        page = self._page("运行管理", "启动、正常停止或重启本控制中心管理的服务。停止时会等待当前请求完成。")
        card = Card()
        heading = QHBoxLayout()
        heading.addWidget(label("本机服务", "cardTitle"))
        heading.addStretch()
        self.management_state = label("● 已停止", "state", True)
        heading.addWidget(self.management_state)
        card.box.addLayout(heading)
        self.management_grid = InfoGrid((
            ("status", "运行状态"), ("pid", "进程编号"),
            ("host", "监听地址"), ("port", "端口"),
            ("started", "启动时间"), ("elapsed", "运行时长"),
            ("version", "版本"), ("health", "健康状态"),
        ))
        card.box.addWidget(self.management_grid)
        self.management_message = label("", "muted", True)
        card.box.addWidget(self.management_message)
        self.start_button = button("启动 SeedLab", self.manager.start, True)
        self.stop_button = button("停止 SeedLab", self.manager.stop)
        self.restart_button = button("重启 SeedLab", self.manager.restart)
        self.open_button = button("打开 SeedLab", self.open_browser)
        card.box.addWidget(ActionRow((self.start_button, self.stop_button, self.restart_button, self.open_button)))
        page.addWidget(card)
        notice = Card()
        notice.box.addWidget(label("正常停止", "sectionTitle"))
        notice.box.addWidget(label("停止服务时会等待当前请求完成，不会删除实验数据。如长时间无法退出，可在确认后强制结束。", "muted", True))
        page.addWidget(notice)
        page.addStretch()

    def _build_network(self):
        page = self._page("网络访问", "选择本机、局域网或远程访问方式；修改后请明确保存设置。")
        self.network_panel = NetworkPanel(self.manager)
        self.network_panel.save_requested.connect(self.save_network)
        page.addWidget(self.network_panel)
        page.addStretch()

    def _build_data(self):
        page = self._page("数据与备份", "检查数据库并创建独立备份；现有数据和历史备份不会被覆盖。")
        self.backup_panel = BackupPanel(self.manager, self.operations)
        self.database_details = self.backup_panel.database_details
        self.database_path = self.backup_panel.database_path
        page.addWidget(self.backup_panel)
        page.addStretch()

    def _build_logs(self):
        page = self._page("日志与诊断", "查看最近运行事件；发生问题时可打开日志目录查看详细记录。")
        tools = QHBoxLayout()
        self.log_state = label("", "muted", True)
        tools.addWidget(self.log_state)
        tools.addStretch()
        tools.addWidget(button("打开日志目录", self.open_logs))
        tools.addWidget(button("刷新", self.refresh_logs))
        page.addLayout(tools)
        self.log_views = []
        for title in ("SeedLab 服务记录", "控制中心记录"):
            card = Card()
            card.box.addWidget(label(title, "cardTitle"))
            view = QPlainTextEdit()
            view.setObjectName("eventLog")
            view.setReadOnly(True)
            view.setMinimumHeight(100)
            view.setMaximumHeight(170)
            view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            card.box.addWidget(view)
            self.log_views.append(view)
            page.addWidget(card)
        page.addWidget(label("诊断包：尚未配置", "muted"))
        page.addStretch()

    def _build_about(self):
        page = self._page("设置与关于", "设置自动备份与保留份数；访问方式在网络访问页面设置。")
        card = Card()
        self.settings_panel = SettingsPanel(self.manager)
        self.settings_panel.save_requested.connect(self.save_backup_settings)
        page.addWidget(self.settings_panel)
        card.box.addWidget(label("SeedLab", "cardTitle"))
        card.box.addWidget(label(f"应用版本：v{VERSION}\n默认端口：8848\n数据库结构版本：c6d91f28a405", None, True))
        card.box.addWidget(label("作者：Steven_Chen / SS_Zhong\n许可：MIT License", "muted", True))
        card.box.addWidget(label("统计分析阶段（Stage 4）尚未开始。", "muted", True))
        page.addWidget(card)
        page.addStretch()

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self.icon, self)
        menu = QMenu(self)
        menu.addAction("打开控制中心", self.restore_window)
        self.tray_open = menu.addAction("打开 SeedLab", self.open_browser)
        menu.addSeparator()
        self.tray_start = menu.addAction("启动 SeedLab", self.manager.start)
        self.tray_stop = menu.addAction("停止 SeedLab", self.manager.stop)
        self.tray_restart = menu.addAction("重启 SeedLab", self.manager.restart)
        menu.addSeparator()
        menu.addAction("退出", self.request_exit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.restore_window() if reason in (
            QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def select_page(self, index):
        self.pages.setCurrentIndex(index)
        for i, nav in enumerate(self.nav_buttons):
            nav.setChecked(i == index)
        if index == 4:
            self.refresh_logs()

    def elapsed(self):
        if not self.manager.started_at:
            return "—"
        seconds = max(0, int((datetime.now() - self.manager.started_at).total_seconds()))
        return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"

    def refresh(self):
        manager = self.manager
        tone = "good" if manager.can_open else "error" if manager.state == State.ERROR else "neutral" if manager.state == State.STOPPED else "progress"
        for item in (self.header_state, self.hero_state, self.management_state):
            item.setText("● " + manager.label)
            item.setProperty("tone", tone)
            item.style().unpolish(item)
            item.style().polish(item)
        self.hero_message.setText(manager.message)
        self.hero_details.setText(f"运行时间 {self.elapsed()}   ·   版本 v{VERSION}   ·   监听 {manager.bind_host}   ·   端口 {manager.port}")
        self.overview_primary.setText("打开 SeedLab" if manager.can_open else "启动 SeedLab")
        self.overview_primary.setEnabled(manager.can_open or manager.can_start)
        self.overview_restart.setEnabled(manager.can_stop)
        self.error_logs.setVisible(manager.state == State.ERROR)
        self.start_button.setEnabled(manager.can_start)
        self.stop_button.setEnabled(manager.can_stop)
        self.restart_button.setEnabled(manager.can_stop)
        self.open_button.setEnabled(manager.can_open)
        health = "正常" if manager.health_ok else "检查中" if manager.state == State.STARTING else "暂时无法连接" if manager.process else "未运行"
        self.service_card.value.setText(health if manager.can_open else manager.label)
        self.service_card.detail.setText(f"运行时间 {self.elapsed()}")
        name, path, size = manager.paths.database_info()
        self.database_card.value.setText(name)
        self.database_card.detail.setText(size)
        self.access_card.value.setText("外部服务" if manager.state == State.EXTERNAL else MODE_LABELS[manager.active_config.access_mode])
        self.access_card.detail.setText(manager.user_url or "请先配置访问地址")
        self.network_panel.refresh()
        self.settings_panel.refresh()
        self.backup_panel.refresh()
        self.database_details.setText(f"文件名：{name}\n文件大小：{size}")
        self.database_path.setText(path)
        pid = str(manager.process.pid) if manager.process else "—"
        started = manager.started_at.strftime("%Y-%m-%d %H:%M:%S") if manager.started_at else "—"
        fields = {"status": manager.label, "pid": pid, "host": manager.bind_host, "port": str(manager.port),
                  "started": started, "elapsed": self.elapsed(), "version": f"v{VERSION}", "health": health}
        for key, value in fields.items():
            self.management_grid.values[key].setText(value)
        self.management_message.setText(manager.message)
        self.log_state.setText("当前状态：" + manager.label)
        for action, enabled in ((self.tray_start, manager.can_start), (self.tray_stop, manager.can_stop),
                                (self.tray_restart, manager.can_stop), (self.tray_open, manager.can_open)):
            action.setEnabled(enabled)
        self.tray.setToolTip("SeedLab · " + manager.label)
        self.check_bootstrap()
        self.recent_events.setText("\n".join(format_event(when, message, overview=True)
                                            for when, message in self.events)
                                   or "最近没有需要处理的问题。")
        if self._exit_after_stop and manager.process is None and not manager.pending_start:
            self.finish_exit()

    def check_bootstrap(self):
        path = self.manager.paths.bootstrap_token
        token = ""
        if self.manager.can_open and self.manager.initialized is not True and path.is_file():
            try:
                token = path.read_text(encoding="utf-8").strip()
            except OSError:
                self.manager.control_log.exception("初始化提示读取失败")
        self.bootstrap.setVisible(bool(token))
        self.token_edit.setText(token)
        if not token:
            self._token_revealed = False
            self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self.reveal_button.setText("显示初始化码")

    def toggle_token(self):
        self._token_revealed = not self._token_revealed
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Normal if self._token_revealed else QLineEdit.EchoMode.Password)
        self.reveal_button.setText("隐藏初始化码" if self._token_revealed else "显示初始化码")

    def copy_token(self):
        if copy_text(self, self.token_edit.text()):
            self.bootstrap_hint.setText("初始化码已复制。请仅用于设置首位管理员，不要向其他人转发。")
        else:
            self.bootstrap_hint.setText("无法写入剪贴板。请显示初始化码后手动复制。")

    def add_event(self, message):
        if not any(term in message for term in ("启动成功", "已停止", "失败", "恢复", "缺失", "被占用", "未通过", "意外退出", "备份完成", "模式已更新", "远程访问", "数据库检查")):
            return
        self.events.insert(0, (datetime.now(), message))
        del self.events[3:]
        self.recent_events.setText("\n".join(format_event(when, text, overview=True) for when, text in self.events))
        if self.pages.currentIndex() == 4:
            self.refresh_logs()

    def overview_action(self):
        self.open_browser() if self.manager.can_open else self.manager.start()

    def open_browser(self, suffix=""):
        if self.manager.can_open:
            QDesktopServices.openUrl(QUrl(self.manager.user_url + (suffix if isinstance(suffix, str) else "")))

    def open_logs(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.manager.paths.logs)))

    def refresh_logs(self):
        for view, name in zip(self.log_views, ("production-server", "control-center")):
            view.setPlainText(user_log_tail(self.manager.paths.logs / f"{name}.log"))
            cursor = view.textCursor()
            cursor.select(QTextCursor.SelectionType.Document)
            spacing = QTextBlockFormat()
            spacing.setLineHeight(145, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            cursor.mergeBlockFormat(spacing)

    def restore_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self._allow_exit:
            event.accept()
            return
        event.ignore()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            if not self._hidden_notice:
                self.tray.showMessage("SeedLab", "SeedLab 控制中心已最小化到系统托盘。", QSystemTrayIcon.MessageIcon.Information, 3000)
                self._hidden_notice = True
        else:
            self.showMinimized()

    def save_network(self, candidate, *, exiting=False):
        restart = False
        if self.manager.process is not None and self.manager.network_settings_changed(candidate) and not exiting:
            dialog = QMessageBox(self)
            dialog.setWindowTitle("保存访问方式")
            dialog.setText("访问方式变更需要重启 SeedLab，当前请求会先完成。")
            save = dialog.addButton("保存并重启", QMessageBox.ButtonRole.AcceptRole)
            dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            dialog.exec()
            if dialog.clickedButton() != save:
                return False
            restart = True
        try:
            self.manager.apply_settings(candidate, restart=restart, exiting=exiting)
        except ConfigError as error:
            QMessageBox.warning(self, "设置未保存", str(error))
            return False
        except OSError:
            self.manager.control_log.exception("运行设置保存失败")
            QMessageBox.warning(self, "设置未保存", "请检查访问设置和配置目录权限后重试；原设置已保留。")
            return False
        self.network_panel.load()
        if self.manager.polling:
            self.network_panel.auto_check()
        return True

    def save_backup_settings(self, candidate):
        try:
            self.manager.apply_settings(candidate)
        except (ConfigError, OSError):
            self.manager.control_log.exception("备份设置保存失败")
            QMessageBox.warning(self, "设置未保存", "请检查配置目录权限，或等待服务启动和停止完成后重试。")
            return False
        self.settings_panel.load()
        return True

    def request_exit(self):
        if self.network_panel.dirty or self.settings_panel.dirty:
            dialog = QMessageBox(self)
            dialog.setWindowTitle("未保存的设置")
            dialog.setText("有未保存的设置。保存后将用于下次启动；退出前仍会正常停止本控制中心启动的服务。")
            save = dialog.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
            discard = dialog.addButton("不保存", QMessageBox.ButtonRole.DestructiveRole)
            dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            dialog.exec()
            if dialog.clickedButton() == save:
                try:
                    candidate = self.network_panel.candidate()
                    if self.settings_panel.dirty:
                        from dataclasses import replace
                        backup = self.settings_panel.candidate()
                        candidate = replace(candidate, auto_backup_enabled=backup.auto_backup_enabled,
                                            auto_backup_retention=backup.auto_backup_retention)
                    if not self.save_network(candidate, exiting=True):
                        return
                    self.settings_panel.load()
                except ConfigError as error:
                    QMessageBox.warning(self, "请检查设置", str(error))
                    return
            elif dialog.clickedButton() != discard:
                return
        if self.manager.process is not None:
            dialog = QMessageBox(self)
            dialog.setWindowTitle("退出控制中心")
            dialog.setText("SeedLab 当前正在运行。退出控制中心前需要停止 SeedLab。")
            stop = dialog.addButton("停止 SeedLab 并退出", QMessageBox.ButtonRole.AcceptRole)
            dialog.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            dialog.exec()
            if dialog.clickedButton() != stop:
                return
            self._exit_after_stop = True
            self.manager.restart_pending = False
            self.manager.stop()
        else:
            self.manager.pending_start = False
            self.finish_exit()

    def stop_timeout_dialog(self):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("服务停止需要更多时间")
        dialog.setText("SeedLab 未能正常停止。继续等待可让正在进行的操作完成；强制结束可能中断正在保存的数据。")
        wait = dialog.addButton("继续等待", QMessageBox.ButtonRole.RejectRole)
        force = dialog.addButton("强制结束", QMessageBox.ButtonRole.DestructiveRole)
        dialog.setDefaultButton(wait)
        dialog.exec()
        self.manager.force_stop() if dialog.clickedButton() == force else self.manager.continue_waiting()

    def finish_exit(self):
        if self._allow_exit:
            return
        self.operations.closing = True
        if self.operations.busy:
            self._exit_after_stop = True
            self.hero_message.setText("正在完成数据检查或备份，完成后退出。")
            return
        self.network_panel.timer.stop()
        self.network_panel.checker.stop()
        self._allow_exit = True
        self.ui_timer.stop()
        self.manager.stop_checks()
        self.tray.hide()
        QApplication.instance().quit()
