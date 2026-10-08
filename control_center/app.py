import argparse
from dataclasses import replace
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from .first_run import FirstRunWizard
from .installation import InstallationStore, validate_location
from .main_window import MainWindow
from .paths import RuntimePaths
from .server_manager import ServerProcessManager
from .single_instance import SingleInstance, instance_name
from .brand import PRODUCT_TITLE, product_icon, configure_windows_brand


def parse_args(arguments=None):
    parser = argparse.ArgumentParser(description="SeedLab 运行控制中心")
    parser.add_argument("--data-root", type=Path, help="显式指定独立数据目录，适用于开发和隔离验证")
    parser.add_argument("--skip-first-run", action="store_true", help="开发者明确使用已有开发路径")
    parser.add_argument("--program-root", type=Path, help="显式指定程序资源位置")
    parser.add_argument("--layout", choices=("development", "portable"))
    parser.add_argument("--startup", action="store_true", help="Windows 登录启动：已部署时留在系统托盘")
    parser.add_argument("--deployment-root", type=Path)
    parser.add_argument("--candidate-id")
    parser.add_argument("--start-server", action="store_true")
    parser.add_argument("--isolated", action="store_true", help="隔离构建验收，不登记 Windows 产品显示信息")
    return parser.parse_args(arguments)


class ApplicationController(QObject):
    def __init__(self, paths, installation, *, skip_first_run=False, explicit_data=False, startup=False,
                 claim_data_root=None, start_server=False):
        super().__init__()
        self.paths, self.installation = paths, installation
        self.window = None
        self.wizard = None
        self.startup = startup
        self.start_server = start_server
        self.claim_data_root = claim_data_root or (lambda paths: True)
        self.activation_redirected = False
        if explicit_data:
            validate_location(paths.data_root, paths, allow_temporary=True)
            self.show_main(paths)
        elif skip_first_run:
            if paths.layout == "portable" and paths.data_root is None:
                raise ValueError("请明确指定数据目录后再跳过部署向导。")
            self.show_main(paths)
        else:
            data = installation.load()
            if data is not None:
                self.show_main(replace(paths, data_root=data))
            else:
                self.wizard = FirstRunWizard(paths, installation)
                self.wizard.completed.connect(lambda selected: self.show_main(selected, auto_start=True))
                self.wizard.show()

    def show_main(self, paths, *, auto_start=False):
        if not self.claim_data_root(paths):
            self.activation_redirected = True
            QTimer.singleShot(0, QApplication.instance().quit)
            return
        self.paths = paths
        manager = ServerProcessManager(paths)
        self.window = MainWindow(manager)
        manager.setParent(self.window)
        manager.control_log.info("[事件] 控制中心已打开。")
        if paths.candidate_id:
            self.window.setEnabled(False)
            self.window.tray.hide()
            self.candidate_timer = QTimer(self)
            self.candidate_timer.setInterval(200)
            stop = paths.deployment_root / "Updates" / paths.candidate_id / "stop.request"
            self.candidate_timer.timeout.connect(lambda: self.window.begin_upgrade_exit() if stop.is_file() else None)
            self.candidate_timer.start()
        elif self.startup and not auto_start:
            if not QSystemTrayIcon.isSystemTrayAvailable():
                self.window.showMinimized()
        else:
            self.window.show()
        if auto_start or self.start_server or paths.candidate_id or manager.config.auto_start_server:
            QTimer.singleShot(0, lambda: manager.start() if manager.can_start else None)

    def activate(self):
        if self.paths.candidate_id:
            return
        if self.window is not None:
            self.window.restore_window()
        elif self.wizard is not None:
            self.wizard.showNormal()
            self.wizard.raise_()
            self.wizard.activateWindow()


def main(arguments=None):
    args = parse_args(arguments)
    paths = RuntimePaths.discover(program_root=args.program_root, data_root=args.data_root, layout=args.layout)
    if not args.isolated:
        configure_windows_brand(paths)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(PRODUCT_TITLE)
    app.setApplicationDisplayName(PRODUCT_TITLE)
    app.setWindowIcon(product_icon())
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    installation = InstallationStore(paths, allow_temporary=args.data_root is not None)
    controller = None
    instances = []
    def close_instances():
        for item in instances:
            item.close()
    def activate_existing():
        if controller is not None:
            controller.activate()
    def claim_data_root(selected):
        item = SingleInstance(instance_name(selected, scope="data"), parent=app)
        if not item.acquire():
            return False
        instances.append(item)
        item.activated.connect(activate_existing)
        return True
    def exception_hook(kind, value, traceback):
        if controller is not None and controller.window is not None:
            controller.window.manager.control_log.error("控制中心发生异常", exc_info=(kind, value, traceback))
        else:
            sys.__excepthook__(kind, value, traceback)
        QMessageBox.critical(None, "运行遇到问题", "控制中心遇到运行问题。请保留数据文件并检查程序或数据目录；若服务仍在运行，请正常停止后再退出。")
    sys.excepthook = exception_hook
    try:
        managed_root = args.deployment_root
        if (managed_root is None and paths.layout == "portable" and paths.program_root.name == "SeedLab"
                and paths.program_root.parent.parent.name == "App"):
            possible = paths.program_root.parents[2]
            if (possible / "state/deployment.json").is_file():
                managed_root = possible
        if managed_root is not None:
            from production_ops import OperationsError
            from production_ops.deployment import DeploymentStore
            from production_ops.database import existing_data
            from app.version import VERSION
            state = DeploymentStore(managed_root).load()
            pending = state["pending"]
            if args.candidate_id:
                if not pending or pending["id"] != args.candidate_id or pending["phase"] != "candidate":
                    raise OperationsError("升级验证信息不匹配，请返回升级助手。")
                selected = pending["target"]
            else:
                if pending:
                    raise OperationsError("上一次升级尚未完成，请通过 SeedLab Launcher 打开升级助手处理。")
                selected = state["current"]
            if Path(selected["program_root"]).resolve() != paths.program_root or selected["version"] != VERSION:
                raise OperationsError("此程序不是当前部署选定的版本，请通过 SeedLab Launcher 启动。")
            if args.data_root and args.data_root.resolve() != Path(state["data_root"]).resolve():
                raise OperationsError("数据位置与部署记录不一致，服务未启动。")
            existing_data(state["data_root"])
            paths = replace(paths, data_root=Path(state["data_root"]), deployment_root=managed_root,
                            candidate_id=args.candidate_id)
            args.data_root = paths.data_root
        elif args.candidate_id:
            raise ValueError("升级验证必须通过独立升级助手启动。")
        instance = SingleInstance(instance_name(paths), parent=app)
        if not instance.acquire():
            return 0
        instances.append(instance)
        app.aboutToQuit.connect(close_instances)
        instance.activated.connect(activate_existing)
        if args.data_root is not None:
            validate_location(args.data_root, paths, allow_temporary=True)
        controller = ApplicationController(paths, installation, skip_first_run=args.skip_first_run,
                                           explicit_data=args.data_root is not None, startup=args.startup,
                                           claim_data_root=claim_data_root, start_server=args.start_server)
        if controller.activation_redirected:
            close_instances()
            return 0
    except Exception:
        close_instances()
        exception_hook(*sys.exc_info())
        return 1
    return app.exec()
