"""Explicit program resources and production data roots; cwd is never a locator."""
from dataclasses import dataclass
from pathlib import Path
import os
import sys
import tempfile
from uuid import uuid4

from app.core.config import Settings, ROOT
from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class RuntimePaths:
    program_root: Path
    python: Path | None = None
    web_root: Path | None = None
    database: Path | None = None
    bootstrap_token: Path | None = None
    logs: Path | None = None
    config_override: Path | None = None
    backups_override: Path | None = None
    data_root: Path | None = None
    layout: str = "development"
    migration_root: Path | None = None
    resource_root: Path | None = None
    deployment_root: Path | None = None
    candidate_id: str | None = None

    def __post_init__(self):
        if self.layout not in ("development", "portable"):
            raise ValueError("Unknown runtime layout")
        program = Path(self.program_root).resolve()
        object.__setattr__(self, "program_root", program)
        object.__setattr__(self, "resource_root", Path(self.resource_root or program).resolve())
        if self.deployment_root is not None:
            object.__setattr__(self, "deployment_root", Path(self.deployment_root).resolve())
        resource = program / ("app" if self.layout == "portable" else "backend")
        if self.web_root is None:
            object.__setattr__(self, "web_root", program / ("app/web" if self.layout == "portable" else "frontend/dist"))
        if self.migration_root is None:
            object.__setattr__(self, "migration_root", resource / ("migrations" if self.layout == "portable" else "alembic"))
        if self.python is None and self.layout == "development":
            object.__setattr__(self, "python", Path(sys.executable))
        if self.data_root is not None:
            data = Path(self.data_root).resolve()
            object.__setattr__(self, "data_root", data)
            for name, relative in (("database", "data/seedlab.db"), ("bootstrap_token", "data/bootstrap.token"),
                                   ("logs", "logs"), ("config_override", "config/seedlab.json"),
                                   ("backups_override", "backups")):
                object.__setattr__(self, name, data / relative)
        elif self.logs is None:
            object.__setattr__(self, "logs", program / "logs")

    @property
    def root(self):
        return self.program_root

    @property
    def config_file(self):
        return self.config_override or self.program_root / "config/seedlab.json"

    @property
    def instance_root(self):
        return self.data_root or self.config_file.parent.parent

    @property
    def installation_file(self):
        return self.program_root / "config/installation.json"

    @property
    def backups(self):
        return self.backups_override or self.program_root / "backups"

    @property
    def server_executable(self):
        return self.program_root / "SeedLabServer.exe"

    @property
    def control_executable(self):
        return self.program_root / "SeedLab Control Center.exe"

    @property
    def launcher_available(self):
        if self.layout == "portable":
            return self.server_executable.is_file()
        return self.python.is_file() and (self.program_root / "scripts/run_prod.py").is_file()

    @classmethod
    def discover(cls, *, program_root=None, data_root=None, layout=None):
        packaged = getattr(sys, "frozen", False)
        layout = layout or ("portable" if packaged else "development")
        program = Path(program_root or (Path(sys.executable).parent if packaged else ROOT)).resolve()
        resources = Path(getattr(sys, "_MEIPASS", program)) if packaged else program
        if data_root is not None or layout == "portable":
            return cls(program, data_root=data_root, layout=layout, resource_root=resources)
        settings = Settings()
        backend = program / "backend"
        url = make_url(settings.seedlab_database_url)
        database = None
        if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
            database = (backend / url.database).resolve()
        return cls(program, program / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"),
                   settings.web_root, database, (backend / settings.seedlab_bootstrap_token_path).resolve(), program / "logs")

    def new_stop_file(self):
        directory = self.data_root / "data/control" if self.data_root is not None else Path(tempfile.gettempdir()) / "SeedLab/control"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{uuid4().hex}.stop"

    def server_command(self, stop_file, settings):
        command = [str(self.server_executable)] if self.layout == "portable" else [str(self.python), "-u", str(self.program_root / "scripts/run_prod.py")]
        command += ["--host", settings.bind_host, "--port", str(settings.port), "--web-root", str(self.web_root),
                    "--migration-root", str(self.migration_root), "--cookie-secure", str(settings.cookie_secure).lower()]
        if self.candidate_id:
            command += ["--candidate-id", self.candidate_id, "--candidate-stop", str(self.deployment_root / "Updates" / self.candidate_id / "stop.request")]
        if self.deployment_root:
            command.append("--existing-data")
        if self.database is not None:
            command += ["--database", str(self.database)]
        if self.bootstrap_token is not None:
            command += ["--bootstrap-token", str(self.bootstrap_token)]
        command += ["--data-root", str(self.instance_root), "--access-mode", settings.access_mode]
        return command + ["--stop-file", str(stop_file)]

    def database_info(self):
        if self.database is None:
            return "未使用本地数据库文件", "—", "—"
        try:
            size = f"{self.database.stat().st_size / 1024 ** 2:.2f} MB" if self.database.is_file() else "尚未创建"
        except OSError:
            size = "暂时无法读取"
        return self.database.name, str(self.database), size
