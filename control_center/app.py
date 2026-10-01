import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from .log_utils import make_logger
from .main_window import MainWindow
from app.core.config import ROOT


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SeedLab")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    logger = make_logger(ROOT / "logs", "control-center")

    def exception_hook(kind, value, traceback):
        logger.error("控制中心发生异常", exc_info=(kind, value, traceback))
        QMessageBox.critical(None, "运行遇到问题", "控制中心遇到运行问题。请打开日志目录查看详细记录；若服务仍在运行，请正常停止后再退出。")

    sys.excepthook = exception_hook
    logger.info("[事件] 控制中心已打开。")
    try:
        window = MainWindow()
    except Exception:
        exception_hook(*sys.exc_info())
        return 1
    window.show()
    return app.exec()
