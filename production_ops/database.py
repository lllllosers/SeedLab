"""Thin AF-1 adapter. Application deployment never implements migrations or restores."""
from pathlib import Path

from app.services.database_upgrade import (database_lease, inspect_schema, validate_database,
    validate_snapshot, prepare_database_for_startup, postflight)
from app.services.database_recovery import require_no_writer
from app.services.sqlite_backup import BackupService
from . import OperationsError
from .deployment import absolute, ordinary


def existing_data(data_root):
    data = absolute(data_root)
    database = ordinary(data / "data/seedlab.db")
    if not database.is_file() or not ordinary(data / "config/seedlab.json").is_file():
        raise OperationsError("现有实验数据目录不完整，升级已停止；不会创建空数据替代。")
    return database, "sqlite:///" + database.as_posix()


def inspect(data_root, migrations, expected=None):
    database, url = existing_data(data_root)
    plan = inspect_schema(url, migrations, allow_create=False)
    validate_database(database)
    if expected is not None and (plan.source_revision != expected or plan.target_revision != expected):
        raise OperationsError("本版升级助手暂不执行跨数据库结构升级，请使用对应版本的专用升级方案。")
    return plan


def protect(data_root, migrations, target_revision, application_version):
    database, url = existing_data(data_root)
    with database_lease(url) as lease:
        require_no_writer(database)
        inspect(data_root, migrations, target_revision)
        snapshot = BackupService(Path(data_root) / "backups").snapshot(database, "before-upgrade",
            source_revision=target_revision, target_revision=target_revision,
            application_version=application_version).path
        validate_snapshot(snapshot, target_revision)
        # Current-schema AF-1 preparation performs postflight without another snapshot.
        prepare_database_for_startup(url, migrations, backup_root=Path(data_root) / "backups",
                                     allow_create=False, lease=lease)
        return snapshot


def verify_offline(data_root, migrations, expected):
    database, url = existing_data(data_root)
    with database_lease(url):
        require_no_writer(database)
        inspect(data_root, migrations, expected)
        postflight(database, expected)
