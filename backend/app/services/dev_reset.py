"""Explicit development-only business reset, with online SQLite backup."""
from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import uuid4

from sqlalchemy import delete, func, inspect, select

from app.core.config import get_settings
from app.db.base import Base
import app.models  # register all tables

PRESERVED = {"users", "sessions", "alembic_version"}
LABELS = {"taxa": "物种", "seed_lots": "种子批次", "experiments": "实验", "experiment_protocols": "实验方案",
          "experiment_materials": "实验材料", "measurement_timepoints": "发芽后测定时间",
          "germination_dishes": "培养皿", "germination_observations": "巡检", "seedling_samples": "幼苗",
          "seedling_measurements": "测定", "audit_logs": "操作记录", "import_jobs": "导入记录",
          "users": "用户", "sessions": "登录会话"}


def require_development():
    if get_settings().seedlab_env != "development":
        raise RuntimeError("正式环境禁止执行开发数据库重置。")


def preview(engine):
    require_development()
    tables = set(inspect(engine).get_table_names())
    unknown = tables - set(Base.metadata.tables) - {"alembic_version"}
    if unknown:
        raise RuntimeError("发现尚未核对的数据表，停止重置：" + "、".join(sorted(unknown)))
    with engine.connect() as connection:
        return {table: connection.scalar(select(func.count()).select_from(Base.metadata.tables[table]))
                for table in Base.metadata.tables if table in tables}


def backup(engine) -> Path:
    path = Path(engine.url.database or "").resolve()
    if engine.dialect.name != "sqlite" or not path.is_file():
        raise RuntimeError("开发重置只支持已有的 SQLite 文件数据库")
    directory = (path.parent.parent if path.parent.name == "data" else path.parent) / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"dev-reset-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.db"
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("备份完整性检查失败，未删除任何业务数据")
    return target


def _delete_business(connection):
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in PRESERVED:
            connection.execute(delete(table))


def reset(engine):
    counts = preview(engine)
    target = backup(engine)
    with engine.begin() as connection:
        _delete_business(connection)
        if connection.exec_driver_sql("PRAGMA foreign_key_check").first():
            raise RuntimeError("重置后的数据关联检查未通过，业务删除已回滚")
    return {"counts": counts, "backup": str(target)}
