"""One guarded SQLite preparation protocol for both production entry points."""
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import tempfile
import warnings

from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from app.services.migrations import migration_config, upgrade_database
from app.services.sqlite_backup import BackupService, check_database, ordinary_path
from app.version import VERSION


logger = logging.getLogger("seedlab.database-upgrade")


class UpgradeError(RuntimeError):
    def __init__(self, message, *, stage, source_revision=None, target_revision=None, snapshot=None):
        super().__init__(message)
        self.stage = stage
        self.source_revision = source_revision
        self.target_revision = target_revision
        self.snapshot = snapshot


@dataclass(frozen=True)
class SchemaPlan:
    state: str
    source_revision: str | None
    target_revision: str


@dataclass(frozen=True)
class UpgradeResult:
    plan: SchemaPlan
    migrated: bool
    snapshot: Path | None = None


@dataclass(frozen=True)
class DatabaseLease:
    database: Path
    handle: object


def database_path(database_url):
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:" or url.query:
        raise UpgradeError("生产启动需要明确的本地数据库文件，请检查数据保存位置。", stage="guard")
    return Path(url.database).absolute()


def plain_file_path(path):
    path = Path(path).absolute()
    for parent in path.parents:
        if parent.exists() and not ordinary_path(parent, directory=True):
            raise OSError("数据保存位置包含重定向或非文件夹路径，请选择普通数据目录。")
    if (path.exists() or path.is_symlink()) and not ordinary_path(path):
        raise OSError("数据文件包含重定向或不是普通文件，请保留原文件并检查保存位置。")
    return path


@contextmanager
def database_lease(database_url):
    """Held for the entire server lifetime; recovery uses the same OS lock."""
    path = plain_file_path(database_path(database_url))
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = plain_file_path(path.with_name(path.name + ".operation.lock"))
    with lock.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise UpgradeError("当前数据正在由 SeedLab 使用或进行维护。请先停止服务，等待维护完成后重试。",
                               stage="busy") from error
        try:
            yield DatabaseLease(path, handle)
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def migration_graph(script_location):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            script = ScriptDirectory.from_config(migration_config(script_location))
            heads = script.get_heads()
            if len(heads) != 1:
                raise ValueError("Expected exactly one migration head")
            ancestors = {revision.revision for revision in script.walk_revisions(head=heads[0])}
            if heads[0] not in ancestors:
                raise ValueError("Incomplete migration graph")
        return heads[0], ancestors
    except Exception as error:
        raise UpgradeError("程序中的数据库升级文件不完整或版本链不明确。请更换完整的程序包后重试。",
                           stage="graph") from error


def read_revision(path, *, immutable=False, allow_empty=False):
    uri = Path(path).as_uri() + "?mode=ro" + ("&immutable=1" if immutable else "")
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if not tables and allow_empty:
            return None
        if "alembic_version" not in tables:
            raise ValueError("Missing database revision")
        rows = list(connection.execute("SELECT version_num FROM alembic_version"))
        if len(rows) != 1 or not isinstance(rows[0][0], str) or not rows[0][0]:
            raise ValueError("Invalid database revision")
        return rows[0][0]


def inspect_schema(database_url, script_location, *, allow_create=True):
    path = plain_file_path(database_path(database_url))
    target, ancestors = migration_graph(script_location)
    if not path.exists():
        if not allow_create:
            raise UpgradeError("已配置的实验数据库不见了。请检查磁盘和部署位置；不会新建空库替代原数据。",
                               stage="guard", target_revision=target)
        return SchemaPlan("new", None, target)
    try:
        source = read_revision(path, allow_empty=allow_create)
    except sqlite3.Error as error:
        raise UpgradeError("实验数据库无法正常读取。请停止服务并保留当前文件和备份，联系管理员检查。",
                           stage="preflight", target_revision=target) from error
    except ValueError as error:
        raise UpgradeError("无法确认实验数据库版本。请保留当前文件，使用匹配的程序或联系管理员检查。",
                           stage="guard", target_revision=target) from error
    if source is None:
        return SchemaPlan("new", None, target)
    if source not in ancestors:
        raise UpgradeError("当前程序不支持这份实验数据库，可能需要更新版本。请使用兼容的程序；原数据不会被升级或覆盖。",
                           stage="guard", source_revision=source, target_revision=target)
    return SchemaPlan("current" if source == target else "upgradable", source, target)


def validate_database(path, *, immutable=False):
    if not check_database(path, immutable=immutable).valid:
        raise sqlite3.DatabaseError("Database integrity or foreign key check failed")


def validate_snapshot(path, revision):
    path = plain_file_path(path)
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("Snapshot must be closed and standalone")
    validate_database(path, immutable=True)
    if read_revision(path, immutable=True) != revision:
        raise ValueError("Snapshot revision differs from the source database")


def postflight(path, revision):
    validate_database(path)
    if read_revision(path) != revision:
        raise ValueError("Unexpected postflight database revision")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        for table in ("experiments", "taxa", "seedling_measurements", "audit_logs"):
            connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()


def write_upgrade_state(snapshot, plan, stage, error=None):
    """Small operation metadata beside its recovery point, never a business table."""
    target = snapshot.with_suffix(".upgrade.json")
    value = {"application_version": VERSION, "source_revision": plan.source_revision,
             "target_revision": plan.target_revision, "snapshot": snapshot.name,
             "stage": stage, "updated_at": datetime.now(timezone.utc).isoformat()}
    if error is not None:
        value["failure"] = {"type": type(error).__name__, "message": str(error)}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".upgrade-", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_database_for_startup(database_url, script_location, *, backup_root=None,
                                 allow_create=True, lease=None):
    path = database_path(database_url)
    if lease is None:
        with database_lease(database_url) as acquired:
            return prepare_database_for_startup(database_url, script_location, backup_root=backup_root,
                                                allow_create=allow_create, lease=acquired)
    if not isinstance(lease, DatabaseLease) or lease.database != path or lease.handle.closed:
        raise UpgradeError("数据库维护未获得独占使用权，请停止服务后重试。", stage="busy")
    plan, snapshot, stage = None, None, "guard"
    try:
        plan = inspect_schema(database_url, script_location, allow_create=allow_create)
        stage = "preflight"
        if path.exists():
            validate_database(path)
        if plan.state == "current":
            stage = "postflight"
            postflight(path, plan.target_revision)
            return UpgradeResult(plan, False)
        if plan.state == "upgradable":
            stage = "backup"
            service = BackupService(backup_root or path.parent / "backups")
            snapshot = service.snapshot(path, "before-upgrade", source_revision=plan.source_revision,
                target_revision=plan.target_revision, application_version=VERSION).path
            stage = "snapshot-validation"
            validate_snapshot(snapshot, plan.source_revision)
            write_upgrade_state(snapshot, plan, "prepared")
        stage = "migration"
        upgrade_database(database_url, script_location)
        stage = "postflight"
        postflight(path, plan.target_revision)
        if snapshot:
            write_upgrade_state(snapshot, plan, "complete")
        return UpgradeResult(plan, True, snapshot)
    except Exception as error:
        if snapshot and plan:
            try:
                write_upgrade_state(snapshot, plan, "failed:" + stage, error)
            except OSError:
                logger.exception("升级状态记录无法保存；数据库和恢复快照仍保留")
        logger.exception("数据库准备失败 stage=%s source=%s target=%s snapshot=%s", stage,
                         plan.source_revision if plan else None, plan.target_revision if plan else None, snapshot)
        if isinstance(error, UpgradeError):
            raise
        messages = {"preflight": "实验数据库检查未通过。请停止服务并保留当前文件和备份，联系管理员检查。",
                    "backup": "升级前数据库备份未完成。请检查备份目录权限和可用空间后重试。",
                    "snapshot-validation": "升级前备份检查未通过，尚未升级。请保留数据库和备份，联系管理员检查。",
                    "migration": "数据库升级未完成。请保留当前数据库、升级前备份和日志，按恢复说明处理后重试。",
                    "postflight": "升级后的数据库检查未通过。请保留当前数据库、升级前备份和日志，联系管理员处理。"}
        raise UpgradeError(messages.get(stage, "数据库准备未完成，请保留现有文件并检查日志。"),
            stage=stage, source_revision=plan.source_revision if plan else None,
            target_revision=plan.target_revision if plan else None, snapshot=snapshot) from error
