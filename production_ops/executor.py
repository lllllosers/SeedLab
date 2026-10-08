"""One local-package executor shared by Bootstrap and the normal Updater."""
import copy
from pathlib import Path
import shutil
from uuid import uuid4

from app.services.database_upgrade import migration_graph
from control_center.log_utils import make_logger
from . import OperationsError
from . import database
from .deployment import CENTER, SERVER, DeploymentStore, atomic_json, ordinary, read_json, separate
from .package import REQUIRED, extract_package
from .runtime import CandidateRuntime
from .windows import closed_program, executable_version, require_stopped


class UpgradeExecutor:
    def __init__(self, root, *, runtime=None, program_guard=closed_program, version_reader=executable_version,
                 progress=lambda text: None):
        self.store = DeploymentStore(root)
        self.runtime = runtime or CandidateRuntime(self.store)
        self.program_guard = program_guard
        self.version_reader = version_reader
        self.progress = progress
        self.log = make_logger(self.store.root / "Logs", "updater")

    def event(self, text):
        self.log.info("[事件] %s", text)
        self.progress(text)

    def stage(self, local_package):
        with self.store.lock():
            state = self.store.load()
            if state["pending"]:
                raise OperationsError("上一次升级尚未结束，请先恢复原版本。")
            job_id = uuid4().hex
            staging = ordinary(self.store.root / "Updates" / job_id / "SeedLab")
            self.event("正在检查升级包并准备新程序，当前版本可继续使用。")
            manifest = extract_package(local_package, staging, state["current"]["version"])
            target = {"version": manifest["target_application_version"],
                      "program_root": str(self.store.root / "App" / ("v" + manifest["target_application_version"]) / "SeedLab"),
                      "build_identity": manifest["build_identity"], "revision": manifest["target_alembic_revision"]}
            separate(state["data_root"], target["program_root"])
            for name in (CENTER, SERVER):
                if self.version_reader(staging / name) != target["version"]:
                    raise OperationsError("升级包中的程序版本与说明不一致。")
            head, _ = migration_graph(staging / "app/migrations")
            if head != target["revision"]:
                raise OperationsError("升级包的数据库说明与程序资源不一致。")
            # This release intentionally supports application-only upgrades. AF-1 remains the database authority.
            database.inspect(state["data_root"], staging / "app/migrations", target["revision"])
            if state["current"]["revision"] != target["revision"]:
                raise OperationsError("此升级涉及数据库结构变化，本版助手尚不支持自动执行，请联系维护人员。")
            pending = {"id": job_id, "phase": "staged", "target": target, "snapshot": None, "message": ""}
            state["pending"] = pending
            self.store.save(state)
            self.event("升级包准备完成。开始升级后将短暂停止 SeedLab。")
            return copy.deepcopy(state)

    def activate(self, *, handoff=None):
        with self.store.lock():
            state = self.store.load()
            pending = state["pending"]
            if not pending or pending["phase"] != "staged":
                raise OperationsError("请先完成升级包检查；中断的升级请先恢复原版本。")
            source = Path(state["current"]["program_root"])
            obsolete = state["previous"]
            candidate_started = False
            try:
                self.event("正在等待原控制中心和服务正常退出。")
                self.runtime.request_handoff(handoff, source)
                with self.program_guard(source):
                    pending["phase"] = "maintenance"
                    self.store.save(state)
                    target = Path(pending["target"]["program_root"])
                    staging = self.store.job(pending) / "SeedLab"
                    self.event("正在检查实验数据库并创建升级前备份。")
                    snapshot = database.protect(state["data_root"], staging / "app/migrations",
                                                pending["target"]["revision"], pending["target"]["version"])
                    pending.update(phase="protected", snapshot=str(snapshot))
                    self.store.save(state)
                    self.event("升级前备份已核验，正在安装新程序。")
                    target = ordinary(target)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        expected = read_json(staging / "app/build-info.json")
                        if (read_json(target / "app/build-info.json") != expected
                                or any(not ordinary(target / name).is_file() for name in REQUIRED)
                                or any(self.version_reader(target / name) != pending["target"]["version"] for name in (CENTER, SERVER))
                                or migration_graph(target / "app/migrations")[0] != pending["target"]["revision"]):
                            raise OperationsError("已有同名版本目录与升级包不一致，原文件已保留，请联系维护人员。")
                        require_stopped(target)
                    else:
                        staging.rename(target)
                    # Only the new slot receives a locator. The existing Data Root never moves.
                    atomic_json(target / "config/installation.json", {"schema_version": 1, "data_root": state["data_root"]})
                    (target.parent / ".seedlab-managed-slot").write_text("SeedLab managed App slot\n", encoding="utf-8")
                    pending["phase"] = "candidate"
                    self.store.save(state)
                    self.event("正在验证新版本控制中心和服务，尚未切换当前版本。")
                    self.runtime.start(state)
                    candidate_started = True
                    self.runtime.healthy(state)
                    self.runtime.stop(state)
                    candidate_started = False
                    database.verify_offline(state["data_root"], target / "app/migrations", pending["target"]["revision"])
                    state.update(previous=state["current"], current=pending["target"], pending=None,
                                 rollback_snapshot=pending["snapshot"])
                    self.store.save(state)  # The only current switch, after candidate and DB checks.
                    self.event("新版本检查完成，当前版本已切换。")
                self.prune_obsolete(obsolete, state)
                self.runtime.launch_current()
                return state
            except Exception as error:
                self.log.exception("升级未完成")
                if candidate_started:
                    try:
                        self.runtime.stop(state)
                    except Exception:
                        self.log.exception("候选程序尚未退出")
                # A successful commit is never rewritten as an uncommitted candidate.
                if state["pending"] is not None:
                    pending.update(phase="failed", message=str(error) if isinstance(error, OperationsError)
                                   else "升级未完成，请保留原程序和数据，打开升级日志检查。")
                    self.store.save(state)
                if isinstance(error, OperationsError):
                    raise
                raise OperationsError("升级未完成，请保留原程序和实验数据，打开升级日志检查。") from error

    def prune_obsolete(self, slot, state):
        if slot is None or slot in (state["current"], state["previous"]):
            return
        expected = self.store.root / "App" / ("v" + slot["version"])
        if Path(slot["program_root"]) != expected / "SeedLab" or not (expected / ".seedlab-managed-slot").is_file():
            return  # An adopted external legacy directory remains owned by its original operator.
        try:
            ordinary(expected)
            separate(state["data_root"], expected)
            require_stopped(expected / "SeedLab")
            for item in expected.rglob("*"):
                ordinary(item)
                if item.name.casefold() in {"data", "backups", "logs"} or item.name.casefold().endswith((".db", ".db-wal", ".db-shm", ".db-journal")):
                    raise OperationsError("更早程序目录包含运行数据，已保留。")
            shutil.rmtree(expected)
        except (OSError, OperationsError):
            self.log.warning("更早且已不参与回退的程序目录未能清理，当前版本和上一版本不受影响。", exc_info=True)

    def rollback(self):
        with self.store.lock():
            state = self.store.load()
            pending = state["pending"]
            restore = state["current"] if pending else state["previous"]
            if restore is None:
                raise OperationsError("没有已记录的上一版本，请保留当前程序和数据并联系维护人员。")
            if pending:
                self.runtime.stop(state)
            require_stopped(state["current"]["program_root"], restore["program_root"])
            migrations = Path(restore["program_root"]) / "app/migrations"
            database.verify_offline(state["data_root"], migrations, restore["revision"])
            if not (Path(restore["program_root"]) / CENTER).is_file():
                raise OperationsError("上一版本程序缺失，尚未改变部署记录。")
            if pending is None:
                state["current"], state["previous"] = state["previous"], state["current"]
            state["pending"] = None
            self.store.save(state)
            self.event("已恢复上一可用程序入口，实验数据保持原样；未恢复任何数据库快照。")
        self.runtime.launch_current()
        return state
