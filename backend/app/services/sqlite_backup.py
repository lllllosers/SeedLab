"""Live SQLite snapshots and conservative retention, independent of the desktop UI."""
from dataclasses import dataclass
from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from uuid import uuid4


LAB_TIMEZONE = timezone(timedelta(hours=8), "Asia/Shanghai")
AUTO_NAME = re.compile(r"seedlab-auto-(\d{8})-(\d{6})(?:-[0-9a-f]{8})?\.db\Z")
MANUAL_NAME = re.compile(r"seedlab-manual-(\d{8})-(\d{6})(?:-[0-9a-f]{8})?\.db\Z")
UPGRADE_NAME = re.compile(r"seedlab-before-upgrade-(\d{8})-(\d{6})-from-[\w.-]+-to-[\w.-]+-app-[\w.-]+-[0-9a-f]{8}(?:-[0-9a-f]{8})?\.db\Z")
RECOVERY_NAME = re.compile(r"seedlab-failed-recovery-(\d{8})-(\d{6})(?:-[0-9a-f]{8})?\.db\Z")
# Only automatic snapshots are eligible for pruning. Recovery evidence is retained.
BACKUP_PATTERNS = {"auto": AUTO_NAME, "manual": MANUAL_NAME,
                   "before-upgrade": UPGRADE_NAME, "failed-recovery": RECOVERY_NAME}


@dataclass(frozen=True)
class DatabaseCheck:
    integrity: tuple
    foreign_keys: tuple

    @property
    def valid(self):
        return self.integrity == (("ok",),) and not self.foreign_keys


@dataclass(frozen=True)
class BackupResult:
    path: Path
    created: bool = True


def check_database(path, *, immutable=False):
    """A live source uses mode=ro; closed snapshots additionally use immutable=1."""
    uri = Path(path).resolve().as_uri() + "?mode=ro" + ("&immutable=1" if immutable else "")
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as connection:
        return DatabaseCheck(tuple(connection.execute("PRAGMA integrity_check")),
                             tuple(connection.execute("PRAGMA foreign_key_check")))


def ordinary_path(path, *, directory=False):
    try:
        info = path.lstat()
        return (not path.is_symlink() and not getattr(info, "st_file_attributes", 0) & 0x400
                and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)))
    except OSError:
        return False


class BackupService:
    def __init__(self, root, *, clock=None):
        self.root = Path(root).absolute()
        self.clock = clock or (lambda: datetime.now(LAB_TIMEZONE))

    def now(self):
        value = self.clock()
        return value.replace(tzinfo=LAB_TIMEZONE) if value.tzinfo is None else value.astimezone(LAB_TIMEZONE)

    def _safe_directory(self, directory, *, create=False):
        # Reject reparse points in every ancestor, including a redirected root.
        for item in reversed((directory, *directory.parents)):
            if item.exists() or item.is_symlink():
                if not ordinary_path(item, directory=True):
                    raise OSError("Backup directory contains a redirected or non-directory path")
            elif create:
                item.mkdir()
            else:
                return False
        return True

    def prepare(self):
        for name in BACKUP_PATTERNS:
            self._safe_directory(self.root / name, create=True)

    def candidates(self, kind):
        if kind not in BACKUP_PATTERNS:
            raise ValueError("Unsupported backup kind")
        directory = self.root / kind
        if not self._safe_directory(directory):
            return []
        pattern = BACKUP_PATTERNS[kind]
        result = []
        for path in directory.iterdir():
            if self._eligible(path, pattern):
                result.append(path)
        return sorted(result, key=lambda path: path.name, reverse=True)

    def _eligible(self, path, pattern):
        match = pattern.fullmatch(path.name)
        if not match or not ordinary_path(path):
            return False
        try:
            datetime.strptime(match[1] + match[2], "%Y%m%d%H%M%S")
            if any(Path(str(path) + suffix).exists() or Path(str(path) + suffix).is_symlink()
                   for suffix in ("-wal", "-shm", "-journal")):
                return False
            return check_database(path, immutable=True).valid
        except (ValueError, OSError, sqlite3.Error):
            return False

    def latest(self):
        return {kind: next(iter(self.candidates(kind)), None) for kind in ("auto", "manual")}

    def prune(self, retention):
        if type(retention) is not int or not 1 <= retention <= 90:
            raise ValueError("Invalid retention")
        removed = []
        for path in self.candidates("auto")[retention:]:
            # Revalidate immediately before deletion; never traverse directories.
            if self._safe_directory(self.root / "auto") and self._eligible(path, AUTO_NAME):
                path.unlink()
                removed.append(path)
        return removed

    def snapshot(self, source, kind="manual", *, source_revision=None,
                 target_revision=None, application_version=None):
        if kind not in BACKUP_PATTERNS:
            raise ValueError("Unsupported backup kind")
        if source is None:
            raise ValueError("No local SQLite database")
        self.prepare()
        directory = self.root / kind
        name = f"seedlab-{kind}-{self.now():%Y%m%d-%H%M%S}"
        if kind == "before-upgrade":
            values = (source_revision, target_revision, application_version)
            if not all(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", value)
                       for value in values):
                raise ValueError("Upgrade snapshot requires valid revision and application identities")
            name += f"-from-{source_revision}-to-{target_revision}-app-{application_version}-{uuid4().hex[:8]}"
        target = directory / (name + ".db")
        while target.exists() or target.is_symlink():
            target = directory / (name + "-" + uuid4().hex[:8] + ".db")
        partial = directory / (name + ".partial-" + uuid4().hex)
        try:
            source_uri = Path(source).resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(source_uri, uri=True, timeout=5) as original:
                with sqlite3.connect(partial) as destination:
                    deadline = time.monotonic() + 120
                    def progress(status, remaining, total):
                        if time.monotonic() > deadline:
                            raise TimeoutError("Online backup exceeded two minutes")
                    original.backup(destination, pages=256, sleep=0.05, progress=progress)
                    destination.execute("PRAGMA journal_mode=DELETE")
            # Connection context managers commit, but do not close connections.
            original.close()
            destination.close()
            if not check_database(partial, immutable=True).valid:
                raise sqlite3.DatabaseError("Snapshot integrity or foreign key check failed")
            with partial.open("r+b") as output:
                output.flush()
                os.fsync(output.fileno())
            self._safe_directory(directory)
            if os.name == "nt":
                os.rename(partial, target)  # Windows rename never overwrites.
            else:
                os.link(partial, target)  # Exclusive atomic publication.
                partial.unlink()
            return BackupResult(target)
        finally:
            # Only our unique unpublished artifact is eligible for cleanup.
            for connection_name in ("original", "destination"):
                connection = locals().get(connection_name)
                if connection is not None:
                    connection.close()
            for suffix in ("", "-wal", "-shm", "-journal"):
                Path(str(partial) + suffix).unlink(missing_ok=True)

    def daily(self, source, retention=14):
        self.prepare()
        date = self.now().strftime("%Y%m%d")
        today = [path for path in self.candidates("auto") if AUTO_NAME.fullmatch(path.name)[1] == date]
        result = BackupResult(today[0], False) if today else self.snapshot(source, "auto")
        self.prune(retention)
        return result
