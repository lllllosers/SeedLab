from PySide6.QtWidgets import QCheckBox, QPushButton, QMessageBox
from .status_card import Card, label


class StartupPanel(Card):
    def __init__(self, startup):
        super().__init__()
        self.startup = startup
        self.box.addWidget(label("Windows 登录启动", "cardTitle"))
        self.enabled = QCheckBox("Windows 登录后启动 SeedLab 控制中心")
        self.box.addWidget(self.enabled)
        self.box.addWidget(label("登录后控制中心留在系统托盘；是否启动 SeedLab 由上方运行设置决定。", "muted", True))
        self.status = label("", "muted", True)
        self.box.addWidget(self.status)
        self.save_button = QPushButton("保存登录启动设置")
        self.save_button.clicked.connect(self.save)
        self.box.addWidget(self.save_button)
        self.enabled.setEnabled(startup.available)
        self.save_button.setEnabled(startup.available)
        self.load()

    def load(self):
        state = self.startup.state()
        self.enabled.setChecked(state.enabled)
        self.status.setText(state.warning or ("已启用 Windows 登录启动。" if state.enabled else "Windows 登录启动已关闭。"))

    def save(self):
        try:
            self.startup.save(self.enabled.isChecked())
        except (OSError, ValueError):
            QMessageBox.warning(self, "登录启动设置未保存", "请检查当前用户权限和程序文件位置后重试；其他程序的登录启动设置不会被修改。")
            return
        self.load()
