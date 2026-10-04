"""Offline, first-business-data import for SeedLab 0.5.1. No migrations."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import sys
import tempfile
import time
from uuid import UUID, uuid4

import legacy_import_core as core
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool
from app.core.config import get_settings
from app.services.germination_execution import execution_summary
from app.services.measurement_query import dashboard, records, task_summary, worklist
from app.services.seedling_measurement import task_data
from app.services.sqlite_backup import ordinary_path
from app.version import VERSION as APP_VERSION

IMPORTER_VERSION = "1.0.0"
COMPATIBILITY = "SeedLab 0.5.1 / d2e7a46b910c"
CONFIRM = "LEGACY-200-202608"
STOP_MESSAGE = "请先通过SeedLab控制中心停止服务，再执行正式历史导入。"
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_path(path, *, directory=False, existing=True):
    core.require(path.is_absolute(), "请使用完整的绝对路径。")
    for ancestor in (path, *path.parents):
        if ancestor.exists() or ancestor.is_symlink():
            core.require(ordinary_path(ancestor, directory=directory if ancestor == path else True),
                         "所选路径包含重定向或不适用的文件，请使用普通文件夹。")
    if existing:
        core.require(path.exists(), "所选文件或文件夹不存在，请检查路径。")
    return path.resolve()


def validate_production_location(root):
    core.require(not root.is_relative_to(Path(tempfile.gettempdir()).resolve()),
                 "临时目录不可用于正式导入，请选择长期保存数据的位置。")
    core.require(not any((parent / ".git").exists() for parent in (root, *root.parents)),
                 "源码仓库内的数据目录不可用于正式导入。")
    blocked = re.compile(r"(?:acceptance|验收|legacy[-_ ]?backfill|投产测试|portable[-_ ]?test|pytest|\.test-temp)", re.I)
    core.require(not any(blocked.search(part) for part in root.parts),
                 "验收或历史回填临时目录不可用于正式导入。")
    core.require(not any(parent.name.casefold() == "backend" for parent in (root, *root.parents)),
                 "开发数据库目录不可用于正式导入。")


def identify_root(root):
    root = safe_path(root, directory=True)
    validate_production_location(root)
    for relative in ("data", "config", "logs", "backups", "backups/manual", "backups/auto", "backups/before-upgrade"):
        safe_path(root / relative, directory=True)
    path = safe_path(root / "data/seedlab.db")
    config_path = safe_path(root / "config/seedlab.json")
    identity_path = safe_path(root / "config/instance.json")
    # Installation locator belongs to Program Root, not Data Root. Validate the
    # actual persisted Data Root settings and deployment identity without creating either.
    config = json.loads(config_path.read_text(encoding="utf-8"))
    sys.path.insert(0, str(core.BACKEND.parent))
    from control_center.config_store import DeploymentSettings
    core.require(set(config) == set(DeploymentSettings.__dataclass_fields__), "运行设置不完整，请检查正式部署。")
    settings = DeploymentSettings.from_dict(config)
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    core.require(set(identity) == {"schema_version", "instance_id", "probe_token"}
                 and type(identity["schema_version"]) is int and identity["schema_version"] == 1
                 and str(UUID(identity["instance_id"])) == identity["instance_id"]
                 and isinstance(identity["probe_token"], str) and len(identity["probe_token"]) >= 32,
                 "部署标识不完整，请检查正式部署。")
    return path, settings


def normalize_schema_sql(sql):
    sql = " ".join(sql.split())
    if not sql.startswith("CREATE TABLE "):
        return sql
    # Alembic batch recreation emits constraints in hash-dependent order.
    # Compare every complete column/constraint clause, ignoring only that order.
    start, end = sql.index("("), sql.rindex(")")
    body = sql[start+1:end]
    clauses, offset, depth, quote = [], 0, 0, None
    for index, character in enumerate(body):
        if quote:
            if character == quote:
                quote = None
        elif character in "'\"`":
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            clauses.append(body[offset:index].strip())
            offset = index + 1
    clauses.append(body[offset:].strip())
    return sql[:start].strip() + " (" + ", ".join(sorted(clauses)) + ")" + sql[end+1:]


def schema_contract(connection):
    return {f"{kind}:{name}": normalize_schema_sql(sql) for kind, name, sql in connection.execute(
        "SELECT type,name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type,name")}


def inspect_connection(connection, owner):
    core.require(connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)],
                 "数据库完整性检查未通过，请保留数据库并联系维护人员。")
    core.require(connection.execute("PRAGMA foreign_key_check").fetchall() == [],
                 "数据库关联检查未通过，请保留数据库并联系维护人员。")
    core.require(connection.execute("SELECT version_num FROM alembic_version").fetchall() == [(core.REVISION,)],
                 f"数据库版本不适用。本工具仅支持 {COMPATIBILITY}。")
    expected = json.loads((RESOURCE_ROOT / "legacy_schema_contract.json").read_text(encoding="utf-8"))
    core.require(schema_contract(connection) == expected, "数据库表结构与已验收版本不一致，请检查部署版本。")
    counts = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in core.BUSINESS_TABLES}
    core.require(not any(counts.values()), "目标库已经存在业务数据，不适合首次历史生产导入；请保留现有数据。")
    core.require(connection.execute("SELECT count(*) FROM users WHERE is_active=1 AND is_admin=1").fetchone()[0] > 0,
                 "请先在正式SeedLab中初始化可用的管理员，再停止服务。")
    owners = connection.execute("SELECT id,is_active FROM users WHERE username=?", (owner,)).fetchall()
    core.require(len(owners) == 1 and owners[0][1] == 1, "负责人不存在、重名或已停用，请填写目标库中唯一可用的用户名。")
    return owners[0][0], counts


def inspect_target(path, owner):
    # Immutable mode never creates SHM/WAL or writes even system state. A live
    # WAL cannot safely be ignored, so reject that state even for dry-run.
    for suffix in ("-wal", "-shm", "-journal"):
        core.require(not Path(str(path) + suffix).exists(), STOP_MESSAGE)
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
        return inspect_connection(connection, owner)


def probe_open_connections(path):
    """Fail closed on Windows sharing violations, including idle SQLite readers."""
    core.require(os.name == "nt", "正式写入工具仅支持Windows。")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                  ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    core.require(handle != ctypes.c_void_p(-1).value, STOP_MESSAGE)
    kernel.CloseHandle(handle)


@contextmanager
def stopped_service(path, settings):
    # Keep the actual configured bind address reserved through backup, import,
    # post-check and recovery. Normal portable startup cannot race the importer.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as guard:
        if os.name == "nt":
            guard.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            guard.bind((settings.bind_host, settings.port))
        except OSError as error:
            raise ValueError(STOP_MESSAGE) from error
        for suffix in ("-wal", "-shm", "-journal"):
            core.require(not Path(str(path) + suffix).exists(), STOP_MESSAGE)
        probe_open_connections(path)
        # Probe a write lock, then close: backup must precede the import transaction.
        with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=0)) as probe:
            try:
                probe.execute("BEGIN IMMEDIATE")
                probe.rollback()
            except sqlite3.Error as error:
                raise ValueError(STOP_MESSAGE) from error
        yield


def snapshot(path, root, phase):
    directory = safe_path(root / "backups/manual", directory=True)
    target = directory / f"seedlab-legacy-{phase}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid4().hex}.db"
    with target.open("xb"):
        pass
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)) as source:
            with closing(sqlite3.connect(target)) as destination:
                deadline = time.monotonic() + 30
                def progress(status, remaining, total):
                    core.require(time.monotonic() <= deadline, "数据库备份超时，导入已停止。")
                source.backup(destination, pages=256, sleep=0.01, progress=progress)
                destination.execute("PRAGMA journal_mode=DELETE")
                core.require(destination.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
                             and destination.execute("PRAGMA foreign_key_check").fetchall() == [],
                             "数据库备份检查未通过，导入已停止。")
        with target.open("r+b") as output:
            os.fsync(output.fileno())
        return {"path": str(target), "size": target.stat().st_size, "sha256": sha256(target), "integrity": "ok"}
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def make_import_engine(path):
    # Unlike normal app make_engine, do not change journal mode or create paths.
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(
        path.as_uri() + "?mode=rw", uri=True, timeout=0), poolclass=NullPool)
    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=0")
        from app.services.local_time import local_date
        connection.create_function("seedlab_local_date", 1,
                                   lambda value: local_date(datetime.fromisoformat(value)).isoformat() if value else None)
    return engine


def reconcile_tasks(db, experiment):
    core.require(experiment.status == "completed" and experiment.ended_at is None,
                 "历史实验状态或结束时间核验未通过。")
    protocol = db.scalar(select(core.ExperimentProtocol).where(core.ExperimentProtocol.experiment_id == experiment.id))
    core.require(protocol.observation_period_days is None and protocol.germination_criterion is None,
                 "历史记录没有观察期限和发芽标准，不得补造。")
    execution = execution_summary(db, experiment.id)
    tasks = task_summary(db, experiment.id)
    current_dashboard = dashboard(db)
    core.require(execution["today_pending_count"] == 0 and execution["sample_count"] == 1665
                 and execution["sown_count"] == 200 and execution["recent_observations"] == []
                 and execution["germination_rate"] is None and execution["cumulative_germinated"] is None,
                 "历史巡检任务或历史事实核验未通过。")
    core.require(all(value == 0 for value in tasks.values()) and task_data(db, experiment.id)["tasks"] == []
                 and current_dashboard == {"due_today_count": 0, "overdue_count": 0, "experiments": []},
                 "当前测定任务必须为空，请检查部署版本。")
    for status in ("pending", "overdue", "due_today", "all"):
        queue = worklist(db, experiment.id, status=status)
        core.require(queue["materials"] == [] and queue["total_materials"] == 0, "当前测定清单核验未通过。")
    core.require(records(db, experiment.id)["total"] == 4955, "历史测定记录查询核验未通过。")
    return {"today_pending_count": 0, **tasks, "dashboard_tasks": 0, "measurement_records": 4955,
            "sown_dishes": 200, "actual_samples": 1665, "status": "completed", "ended_at": None}


def restore_pre_import(path, backup, owner):
    core.require(sha256(backup["path"]) == backup["sha256"], "导入前备份校验失败，请保留数据库和备份。")
    probe_open_connections(path)
    with closing(sqlite3.connect(Path(backup["path"]).as_uri() + "?mode=ro&immutable=1", uri=True)) as source:
        with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=0)) as destination:
            source.backup(destination)
            inspect_connection(destination, owner)


def apply_import(data, path, root, owner, source, report, *, finish=lambda: None):
    report["pre_backup"] = snapshot(path, root, "pre-import")
    engine = make_import_engine(path)
    committed = False
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                raw = connection.connection.driver_connection
                owner_id, _ = inspect_connection(raw, owner)
                with Session(bind=connection) as db:
                    experiment = core.insert_legacy(db, data, owner_id, production=True)
                    report["actual_experiment_code"] = experiment.code
                    report["database"] = core.reconcile_database(db, data, experiment, expected_status="completed")
                    report["workbook"] = core.reconcile_workbook(core.build(db, [experiment.id]), data)
                    report["task_semantics_before_commit"] = reconcile_tasks(db, experiment)
                    core.require(raw.execute("PRAGMA foreign_key_check").fetchall() == [], "数据库关联核验未通过。")
                    report["source_sha_after"] = sha256(source)
                    core.require(report["source_sha_after"] == core.SOURCE_SHA256, "原始Excel在核验期间发生变化，导入已停止。")
                connection.commit()
                committed = True
            except BaseException:
                connection.rollback()
                raise
        with engine.connect() as connection, Session(bind=connection) as db:
            experiment = db.scalar(select(core.Experiment))
            report["task_semantics_after_commit"] = reconcile_tasks(db, experiment)
        report["post_backup"] = snapshot(path, root, "post-import")
        report["source_sha_after"] = sha256(source)
        core.require(report["source_sha_after"] == core.SOURCE_SHA256, "原始Excel在核验期间发生变化，已恢复导入前数据。")
        finish()
    except BaseException:
        engine.dispose()
        if committed:
            restore_pre_import(path, report["pre_backup"], owner)
            report["recovery"] = "PRE-IMPORT BACKUP restored and verified"
        else:
            report["recovery"] = "transaction rolled back"
        raise
    finally:
        engine.dispose()


def provenance():
    path = RESOURCE_ROOT / "legacy_build_provenance.json"
    return json.loads(path.read_text(encoding="utf-8"))["git_commit"] if path.exists() else "unpackaged-development"


def write_reports(directory, report):
    directory.mkdir(parents=True, exist_ok=True)
    for suffix, value in (("json", json.dumps(report, ensure_ascii=False, indent=2)),
                          ("md", "# SeedLab 历史导入报告\n\n```json\n" + json.dumps(report, ensure_ascii=False, indent=2) + "\n```\n")):
        temporary = directory / f".report-{uuid4().hex}.tmp"
        try:
            with temporary.open("x", encoding="utf-8") as output:
                output.write(value + "\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, directory / f"legacy-import-report.{suffix}")
        finally:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    # Frozen Windows consoles and redirected pipes otherwise choose different
    # legacy encodings. Reports and captured output always use UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="SeedLab 200份历史数据维护工具 1.0.0。默认只读预核验；正式写入前必须停止SeedLab服务。")
    parser.add_argument("--version", action="version", version=f"SeedLabLegacyImport {IMPORTER_VERSION}")
    parser.add_argument("--source", type=Path, required=True, help="原始历史Excel的绝对路径；只读且必须通过固定SHA校验")
    parser.add_argument("--data-root", type=Path, required=True, help="已初始化管理员、业务为空的正式SeedLab数据目录绝对路径")
    parser.add_argument("--owner", required=True, help="目标库中唯一可用的实验负责人用户名")
    parser.add_argument("--apply", action="store_true", help="正式导入；同时需要 --confirm LEGACY-200-202608")
    parser.add_argument("--confirm", help="正式导入确认令牌 LEGACY-200-202608")
    parser.add_argument("--output-dir", type=Path, help="独立报告目录绝对路径；必须在Data Root之外且为空")
    args = parser.parse_args(argv)
    report = {"importer_version": IMPORTER_VERSION, "importer_git_commit": provenance(),
              "compatible_seedlab": "0.5.1", "compatible_alembic_revision": core.REVISION,
              "target_compatibility": COMPATIBILITY, "mode": "apply" if args.apply else "dry-run",
              "timestamp": datetime.now(timezone.utc).astimezone(core.ZoneInfo("Asia/Shanghai")).isoformat(),
              "source_path": str(args.source), "data_root": str(args.data_root), "owner": args.owner,
              "planned_experiment_code": "GER-202608-001", "experiment_status": "completed", "ended_at": None,
              "pre_backup": None, "post_backup": None, "final_result": "FAIL"}
    output = None
    try:
        core.require(APP_VERSION == "0.5.1", "工具所附SeedLab逻辑版本不适用，请使用正式构建。")
        core.require(not args.apply or args.confirm == CONFIRM, "正式写入需要同时提供 --apply 和 --confirm LEGACY-200-202608。")
        core.require(not args.confirm or args.apply, "确认令牌仅用于正式导入；预核验请移除 --confirm。")
        os.environ["SEEDLAB_TIMEZONE"] = "Asia/Shanghai"
        get_settings.cache_clear()
        source = safe_path(args.source)
        report["source_sha"] = sha256(source)
        data = core.read_source(source)
        report["source_counts"] = data.metrics
        report["counts"] = {"Taxon": 198, "SeedLot": 200, "Material": 200, "Dish": 200,
                            "Observation": 0, "Sample": 1665, "Measurement": 4955}
        report["slot_closure"] = {"planned_sample_slots": 2000, "absent_samples": 335,
                                  "actual_sample_dag_slots": 4995, "unmeasured_actual_slots": 40,
                                  "absent_sample_measurement_slots": 1005, "planned_measurement_slots": 6000}
        path, settings = identify_root(args.data_root)
        root = path.parent.parent
        report["db_path"] = str(path)
        output = args.output_dir or ((Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()) /
                                     f"legacy-import-output-{uuid4().hex}")
        output = safe_path(output, directory=True, existing=False)
        core.require(not output.is_relative_to(root) and not root.is_relative_to(output), "报告必须保存到Data Root之外的独立目录。")
        core.require(not output.exists() or not any(output.iterdir()), "报告目录已有文件，请选择新的空目录。")
        # Reserve the report names before any apply; a failed report path cannot
        # become a successful but undocumented production import.
        output.mkdir(parents=True, exist_ok=True)
        with (output / ".write-check").open("x"):
            pass
        (output / ".write-check").unlink()
        before = sha256(path)
        report["db_sha_before"] = before
        _, counts = inspect_target(path, args.owner)
        report["empty_business_counts"] = counts
        if args.apply:
            with stopped_service(path, settings):
                def finish():
                    report["final_result"] = "PASS"
                    write_reports(output, report)
                apply_import(data, path, root, args.owner, source, report, finish=finish)
        else:
            report["source_sha_after"] = sha256(source)
            report["db_sha_after"] = sha256(path)
            core.require(report["db_sha_after"] == before and report["source_sha_after"] == core.SOURCE_SHA256,
                         "预核验期间文件发生变化，请停止服务并重新核验。")
            report["zero_database_writes"] = True
            report["final_result"] = "PASS"
            write_reports(output, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"{'正式导入完成' if args.apply else '只读预核验通过，数据库未写入'}。报告：{output}")
        return 0
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        message = str(error) if isinstance(error, (ValueError, FileNotFoundError)) else "维护检查未完成，请保留数据库、备份和报告并联系维护人员。"
        report["final_result"] = "FAIL"
        report["error"] = message
        if output is not None:
            try:
                write_reports(output, report)
            except Exception:
                pass
        print(f"导入停止：{message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
