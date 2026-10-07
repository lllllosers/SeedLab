"""Explicit offline recovery; preserve the failed database before publication."""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from app.services.database_upgrade import (UpgradeError, database_lease, database_path,
    migration_graph, plain_file_path, read_revision, validate_snapshot)
from app.services.sqlite_backup import BackupService


@dataclass(frozen=True)
class RecoveryResult:
    database: Path
    revision: str
    preserved: Path


def require_no_writer(path):
    if os.name == "nt":
        # A zero-sharing read handle detects even an idle external SQLite
        # connection without asking SQLite to recover/checkpoint failed files.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise UpgradeError("数据库仍被其他程序使用或无法独占打开。请关闭相关程序后重试；原文件未替换。",
                               stage="recovery-busy")
        kernel.CloseHandle(handle)
        return
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as inspection:
            inspection.execute("PRAGMA schema_version").fetchone()
        with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=0)) as connection:
            connection.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
            connection.execute("BEGIN EXCLUSIVE")
            connection.rollback()
    except sqlite3.DatabaseError as error:
        # A corrupt closed database can still be preserved byte-for-byte. Lock,
        # permission and I/O errors are never treated as corruption.
        if (getattr(error, "sqlite_errorcode", -1) & 255) not in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
            raise UpgradeError("数据库仍被其他程序使用或无法独占打开。请关闭相关程序后重试；原文件未替换。",
                               stage="recovery-busy") from error


def restore_database(database_url, snapshot, script_location, *, backup_root, confirm_stopped=False):
    if not confirm_stopped:
        raise UpgradeError("恢复前须停止 SeedLab 和所有数据库工具，并明确确认恢复操作。原文件尚未替换。",
                           stage="recovery-confirmation")
    path = plain_file_path(database_path(database_url))
    snapshot = plain_file_path(snapshot)
    if not path.is_file() or path == snapshot:
        raise UpgradeError("请选择现有实验数据库和独立恢复备份，原文件尚未替换。", stage="recovery-validation")
    with database_lease(database_url):
        try:
            target, ancestors = migration_graph(script_location)
            revision = read_revision(snapshot, immutable=True)
            if revision not in ancestors:
                raise ValueError("Recovery revision is unsupported by this program")
            validate_snapshot(snapshot, revision)
        except Exception as error:
            raise UpgradeError("恢复备份无法读取、检查未通过或与当前程序不兼容。请选择经过核验的备份；原数据库未替换。",
                               stage="recovery-validation") from error
        require_no_writer(path)
        service = BackupService(backup_root)
        directory = service.root / "failed-recovery"
        service._safe_directory(directory, create=True)
        archive = directory / f"seedlab-failed-recovery-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid4().hex}"
        candidate = plain_file_path(path.with_name(path.name + ".restore-" + uuid4().hex + ".partial"))
        moved = []
        published = False
        try:
            with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro&immutable=1", uri=True)) as original:
                with closing(sqlite3.connect(candidate)) as replacement:
                    original.backup(replacement)
                    replacement.execute("PRAGMA journal_mode=DELETE")
            validate_snapshot(candidate, revision)
            with candidate.open("r+b") as output:
                output.flush()
                os.fsync(output.fileno())
            # SeedLab's lifetime lease is held. The administrator also confirms
            # external SQLite tools are closed; detect an active writer again.
            require_no_writer(path)
            archive.mkdir()
            for suffix in ("", "-wal", "-shm", "-journal"):
                item = Path(str(path) + suffix)
                if item.exists() or item.is_symlink():
                    plain_file_path(item)
                    destination = archive / item.name
                    os.rename(item, destination)
                    moved.append((item, destination))
            if os.name == "nt":
                os.rename(candidate, path)  # Refuse a concurrently created target.
            else:
                os.link(candidate, path)
                candidate.unlink()
            published = True
            validate_snapshot(path, revision)
            (archive / "recovery.json").write_text(json.dumps({"snapshot": str(snapshot),
                "restored_revision": revision, "program_target_revision": target,
                "restored_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False, indent=2), encoding="utf-8")
            return RecoveryResult(path, revision, archive)
        except Exception as error:
            # Before publication only, put moved files back when their original
            # paths are still absent. Never overwrite a new file or remove evidence.
            if not published:
                for original, preserved in reversed(moved):
                    if not original.exists() and preserved.exists():
                        os.rename(preserved, original)
            raise UpgradeError("数据库恢复未完成。请保留当前数据库、选定备份和恢复保留目录，检查日志后处理；不会自动启动服务。",
                               stage="recovery", source_revision=revision, target_revision=target,
                               snapshot=snapshot) from error
        finally:
            for suffix in ("", "-wal", "-shm", "-journal"):
                Path(str(candidate) + suffix).unlink(missing_ok=True)
