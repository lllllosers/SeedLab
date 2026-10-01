"""Installation locator and conservative production directory initialization."""
from dataclasses import dataclass
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import socket

from alembic.script import ScriptDirectory
from alembic.util import CommandError

from app.services.migrations import migration_config, upgrade_database
from app.services.sqlite_backup import check_database, ordinary_path
from .config_store import ConfigStore, DeploymentSettings
from app.services.runtime_identity import deployment_identity


class InstallationError(ValueError):
    pass


def validate_location(path, paths, *, allow_temporary=False):
    if not isinstance(path, (str, Path)) or not str(path).strip() or not Path(path).is_absolute():
        raise InstallationError("请选择完整的数据保存位置。")
    original = Path(path)
    path = original.resolve()
    if path.exists() and not path.is_dir():
        raise InstallationError("所选位置是文件，请选择文件夹。")
    for resource in (paths.program_root, paths.web_root, paths.migration_root):
        resource = resource.resolve()
        if path.is_relative_to(resource) or resource.is_relative_to(path):
            raise InstallationError("数据目录必须与程序及运行资源分开，请选择程序目录旁的独立文件夹。")
    temporary = Path(tempfile.gettempdir()).resolve()
    if not allow_temporary and path.is_relative_to(temporary):
        raise InstallationError("临时目录中的数据可能被清理，请选择长期保存数据的位置。")
    # No redirected ancestor: the displayed folder must be the actual storage location.
    for ancestor in (original, *original.parents):
        if ancestor.exists() and not ordinary_path(ancestor, directory=True):
            raise InstallationError("数据目录包含重定向位置，请选择普通文件夹。")
    return path


class InstallationStore:
    def __init__(self, paths, *, allow_temporary=False):
        self.paths = paths
        self.path = paths.installation_file
        self.allow_temporary = allow_temporary
        self.warning = ""

    def load(self):
        self.warning = ""
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if (not isinstance(value, dict) or set(value) != {"schema_version", "data_root"}
                    or type(value["schema_version"]) is not int or value["schema_version"] != 1):
                raise InstallationError("部署定位文件内容不受支持。")
            data = validate_location(value["data_root"], self.paths, allow_temporary=self.allow_temporary)
            if not data.is_dir():
                raise InstallationError("已配置的数据目录不存在，请检查磁盘或重新选择。")
            if not (data / "data/seedlab.db").is_file() or not (data / "config/seedlab.json").is_file():
                raise InstallationError("已配置的数据目录不完整，请检查磁盘；现有文件不会被覆盖。")
            return data
        except (OSError, ValueError, TypeError):
            self.warning = "部署位置无法读取，原文件已保留。请检查磁盘或重新完成部署设置。"
            return None

    def save(self, data_root):
        data_root = validate_location(data_root, self.paths, allow_temporary=self.allow_temporary)
        if not data_root.is_dir():
            raise InstallationError("数据目录尚未准备完成，部署位置未保存。")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".installation-", suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                json.dump({"schema_version": 1, "data_root": str(data_root)}, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        self.warning = ""


@dataclass(frozen=True)
class DataInspection:
    existing: bool
    settings: DeploymentSettings | None = None
    has_users: bool = False
    revisions: tuple = ()


def probe_writable(path):
    existing = path
    while not existing.exists():
        existing = existing.parent
    try:
        with tempfile.TemporaryFile(dir=existing) as output:
            output.write(b"SeedLab directory check")
            output.flush()
    except OSError as error:
        raise InstallationError("所选目录无法写入，请选择有写入权限的位置。") from error


def ensure_port_available(settings):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind((settings.bind_host, settings.port))
    except OSError as error:
        raise InstallationError(f"访问端口 {settings.port} 已被占用。请返回访问方式步骤修改端口，"
                                "或退出向导后在原入口停止占用服务；不会使用另一份服务。") from error


def inspect_data_root(paths, *, allow_temporary=False):
    root = validate_location(paths.data_root, paths, allow_temporary=allow_temporary)
    probe_writable(root)
    if not root.exists() or not any(root.iterdir()):
        return DataInspection(False)
    if not paths.database.is_file() or not paths.config_file.is_file():
        raise InstallationError("该目录已有文件，但不是完整的 SeedLab 数据目录。请选择空文件夹或完整数据目录；现有文件不会被覆盖。")
    if not ordinary_path(paths.database) or not ordinary_path(paths.config_file):
        raise InstallationError("现有数据文件包含重定向位置，请保留文件并选择普通数据目录。")
    try:
        settings = DeploymentSettings.from_dict(json.loads(paths.config_file.read_text(encoding="utf-8")))
        if not check_database(paths.database).valid:
            raise InstallationError("现有数据库检查未通过，请保留文件和备份，选择其他位置。")
        with closing(sqlite3.connect(paths.database.as_uri() + "?mode=ro", uri=True)) as connection:
            revisions = tuple(row[0] for row in connection.execute("SELECT version_num FROM alembic_version"))
            has_users = connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None
        script = ScriptDirectory.from_config(migration_config(paths.migration_root))
        if len(revisions) != 1 or script.get_revision(revisions[0]) is None:
            raise InstallationError("无法识别现有数据库版本，请保留文件并检查程序版本。")
        return DataInspection(True, settings, has_users, revisions)
    except (OSError, ValueError, sqlite3.Error, CommandError) as error:
        if isinstance(error, InstallationError):
            raise
        raise InstallationError("现有数据目录检查未通过，请保留文件并检查数据库及运行设置。") from error


def initialize_data_root(paths, settings, installation, *, reuse=False, progress=lambda message: None):
    progress("正在检查数据目录…")
    try:
        probe_writable(installation.path.parent)
    except InstallationError as error:
        raise InstallationError("当前程序目录不可写，请将 SeedLab 文件夹移动到有写入权限的位置后重试。") from error
    inspection = inspect_data_root(paths, allow_temporary=installation.allow_temporary)
    if inspection.existing and not reuse:
        raise InstallationError("发现已有 SeedLab 数据目录，请明确选择使用现有数据。")
    if reuse and not inspection.existing:
        raise InstallationError("所选目录已发生变化，请重新检查后再继续。")
    if inspection.existing:
        settings = inspection.settings  # Preserve the existing deployment configuration.
    ensure_port_available(settings)  # Before any persistent data/config writes.
    if not inspection.existing:
        progress("正在准备数据、备份与日志目录…")
        for relative in ("data", "config", "logs", "backups/auto", "backups/manual", "backups/before-upgrade"):
            (paths.data_root / relative).mkdir(parents=True, exist_ok=True)
        probe_writable(paths.data_root)
        progress("正在保存运行设置…")
        ConfigStore(paths.config_file).save(settings)
    progress("正在准备实验数据库…")
    upgrade_database("sqlite:///" + paths.database.as_posix(), paths.migration_root)
    progress("正在检查数据库…")
    if not check_database(paths.database).valid:
        raise InstallationError("数据库检查未通过，部署未完成。请保留当前文件并检查日志。")
    from app.core.config import Settings
    from app.core.bootstrap import ensure_bootstrap_token
    from app.db.session import make_engine
    from sqlalchemy.orm import Session
    deployment_identity(paths.instance_root)
    engine = make_engine("sqlite:///" + paths.database.as_posix())
    try:
        with Session(engine) as db:
            ensure_bootstrap_token(db, Settings(_env_file=None,
                seedlab_bootstrap_token_path=str(paths.bootstrap_token)), announce=False)
    finally:
        engine.dispose()
    progress("正在确认部署位置…")
    installation.save(paths.data_root)  # The only deployment-complete marker, always last.
    return paths


def suggested_data_root(program_root):
    suggested = program_root.parent / "SeedLabData"
    try:
        probe_writable(suggested)
        return suggested
    except InstallationError:
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "SeedLabData"
