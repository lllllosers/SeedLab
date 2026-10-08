"""Serialized background database work; failures never change server ownership/state."""
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from app.services.sqlite_backup import BackupService, check_database
from .server_manager import State


class JobSignals(QObject):
    finished = Signal(object, object)


class Job(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = JobSignals()

    def run(self):
        try:
            self.signals.finished.emit(self.operation(), None)
        except Exception as error:
            self.signals.finished.emit(None, error)


class Operations(QObject):
    changed = Signal()

    def __init__(self, manager, *, service=None, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.service = service or BackupService(manager.paths.backups)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.busy = False
        self.kind = ""
        self.error = ""
        self.database_status = "尚未检查"
        self.latest = {"auto": None, "manual": None}
        self._job = None
        self._seen_process = None
        self._pending_auto = False
        self.closing = False
        manager.changed.connect(self.observe_server)
        if manager.polling:
            QTimer.singleShot(0, self.scan)

    def _begin(self, kind, operation):
        if self.busy or self.closing:
            return False
        self.kind, self.busy, self.error = kind, True, ""
        self._job = Job(operation)
        self._job.signals.finished.connect(self._finished)
        self.pool.start(self._job)
        self.changed.emit()
        return True

    def scan(self):
        self._begin("scan", self.service.latest)

    def check(self):
        self._begin("check", lambda: check_database(self.manager.paths.database))

    def manual(self):
        self._begin("manual", lambda: self.service.snapshot(self.manager.paths.database))

    def observe_server(self):
        manager = self.manager
        if manager.process is None:
            self._seen_process = None
            self._pending_auto = False
        elif manager.state == State.RUNNING and manager.process is not self._seen_process:
            self._seen_process = manager.process
            if manager.config.auto_backup_enabled and not manager.paths.candidate_id:
                self._pending_auto = True
                self._try_auto()

    def _try_auto(self):
        if (self._pending_auto and not self.busy and not self.closing
                and self.manager.process is not None and self.manager.state == State.RUNNING):
            self._pending_auto = False
            self._begin("auto", lambda: self.service.daily(self.manager.paths.database,
                                                         self.manager.config.auto_backup_retention))

    @Slot(object, object)
    def _finished(self, result, error):
        kind = self.kind
        self.busy, self._job = False, None
        if error is not None:
            self.manager.control_log.error("数据操作失败 (%s)", kind,
                                          exc_info=(type(error), error, error.__traceback__))
            self.error = {"check": "数据库检查未通过，请停止录入并保留当前文件和备份。",
                          "manual": "手工备份失败，请检查目录权限和可用空间后重试。",
                          "auto": "今日自动备份失败，请检查数据与备份页面。",
                          "scan": "备份目录无法读取，请检查目录权限。"}[kind]
            if kind == "check":
                self.database_status = "需要检查"
            self.manager._event(self.error)
        elif kind == "scan":
            self.latest = result
        elif kind == "check":
            self.database_status = "正常" if result.valid else "需要检查"
            if not result.valid:
                self.error = "数据库检查未通过，请停止录入并保留当前文件和备份。"
                self.manager.control_log.error("数据库检查未通过：%r", result)
            self.manager._event("数据库检查正常。" if result.valid else self.error)
        else:
            self.latest[kind] = result.path
            if result.created:
                self.manager._event("今日自动备份完成。" if kind == "auto" else "手工备份完成。")
        self.changed.emit()
        self._try_auto()
