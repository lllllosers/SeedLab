from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import hash_password
from app.core.config import get_settings
from app.db.session import get_db, make_engine
from app.main import app
from app.models import User


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("SEEDLAB_DATABASE_URL", url)
    monkeypatch.setenv("SEEDLAB_BOOTSTRAP_TOKEN_PATH", str(tmp_path / "bootstrap.token"))
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(config, "head")
    engine = make_engine(url)
    local = sessionmaker(bind=engine, expire_on_commit=False)
    with local() as db:
        db.add(User(username="admin", display_name="管理员", password_hash=hash_password("test-password-123"), is_admin=True))
        db.commit()

    def override_db() -> Iterator[Session]:
        with local() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()
    get_settings.cache_clear()


@pytest.fixture
def auth_client(client: TestClient) -> tuple[TestClient, dict[str, str]]:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "test-password-123"})
    assert response.status_code == 200
    return client, {"X-CSRF-Token": response.json()["csrf_token"]}
