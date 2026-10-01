from dataclasses import dataclass
from pathlib import Path
import os
import tempfile
from uuid import uuid4

from app.core.config import Settings, ROOT
from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    python: Path
    web_root: Path
    database: Path | None
    bootstrap_token: Path
    logs: Path

    @classmethod
    def discover(cls):
        settings = Settings()
        backend = ROOT / "backend"
        url = make_url(settings.seedlab_database_url)
        database = None
        if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:":
            database = (backend / url.database).resolve()
        return cls(ROOT, ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"),
                   settings.web_root, database, (backend / settings.seedlab_bootstrap_token_path).resolve(), ROOT / "logs")

    def new_stop_file(self) -> Path:
        directory = Path(tempfile.gettempdir()) / "SeedLab" / "control"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{uuid4().hex}.stop"

    def command(self, stop_file: Path, host="127.0.0.1", port=8848):
        return [str(self.python), "-u", str(self.root / "scripts/run_prod.py"), "--host", host,
                "--port", str(port), "--web-root", str(self.web_root), "--stop-file", str(stop_file)]

    def database_info(self):
        if self.database is None:
            return "未使用本地数据库文件", "—", "—"
        try:
            size = f"{self.database.stat().st_size / 1024 ** 2:.2f} MB" if self.database.is_file() else "尚未创建"
        except OSError:
            size = "暂时无法读取"
        return self.database.name, str(self.database), size
