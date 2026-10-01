from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    seedlab_env: str = "development"
    seedlab_database_url: str = "sqlite:///./data/seedlab.db"
    seedlab_bootstrap_token_path: str = "./data/bootstrap.token"
    seedlab_session_hours: int = 12
    seedlab_cookie_secure: bool = False
    seedlab_timezone: str = "Asia/Shanghai"
    seedlab_web_root: Path = Path("frontend/dist")

    @property
    def web_root(self) -> Path:
        """Relative web paths are anchored to the repository, not the shell cwd."""
        return (ROOT / self.seedlab_web_root).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
