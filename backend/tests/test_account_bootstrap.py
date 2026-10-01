from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import check_password
from app.core.config import get_settings
from app.db.session import get_db, make_engine
from app.main import create_app
from app.models import AuditLog, SessionToken, User


@pytest.fixture
def empty_client(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    token_file = tmp_path / "bootstrap.token"
    monkeypatch.setenv("SEEDLAB_DATABASE_URL", url)
    monkeypatch.setenv("SEEDLAB_BOOTSTRAP_TOKEN_PATH", str(token_file))
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(config, "head")
    engine = make_engine(url)
    local = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with local() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, local, token_file
    app.dependency_overrides.clear()
    engine.dispose()
    get_settings.cache_clear()


def bootstrap_body(token, password="eight123"):
    return {"bootstrap_token": token, "username": "first-admin", "display_name": "首位管理员",
            "password": password, "confirm_password": password}


def test_setup_status_token_first_admin_audit_and_one_time_use(empty_client):
    client, local, token_file = empty_client
    token = token_file.read_text(encoding="utf-8").strip()
    assert len(token) >= 40
    assert client.get("/api/setup/status").json() == {"initialized": False}
    assert token not in str(client.get("/api/setup/status").json())
    assert client.post("/api/setup/bootstrap", json=bootstrap_body("wrong-token")).status_code == 403
    assert client.post("/api/setup/bootstrap", json=bootstrap_body(token, "1234567")).status_code == 422
    response = client.post("/api/setup/bootstrap", json=bootstrap_body(token))
    assert response.status_code == 201, response.text
    assert response.json()["user"]["is_admin"] is True
    assert response.json()["user"]["must_change_password"] is False
    assert response.json()["csrf_token"]
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/setup/status").json() == {"initialized": True}
    assert not token_file.exists()
    assert client.post("/api/setup/bootstrap", json=bootstrap_body(token)).status_code == 409
    with local() as db:
        user = db.scalar(select(User))
        assert check_password(user.password_hash, "eight123")
        assert user.password_hash.startswith("$argon2")
        assert db.scalar(select(SessionToken).where(SessionToken.user_id == user.id))
        audit = db.scalars(select(AuditLog)).all()
        assert len(audit) == 1
        assert all(secret not in str((row.before, row.after)) for row in audit
                   for secret in (token, "eight123", user.password_hash))


def test_bootstrap_competing_requests_only_one_wins(empty_client):
    client, local, token_file = empty_client
    token = token_file.read_text(encoding="utf-8").strip()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post("/api/setup/bootstrap", json=bootstrap_body(token)).status_code,
                                range(2)))
    assert sorted(results) == [201, 409]
    with local() as db:
        assert len(db.scalars(select(User)).all()) == 1


def test_member_forced_change_blocks_business_then_clears_all_sessions(auth_client):
    client, admin_headers = auth_client
    response = client.post("/api/users", json={"username": "member", "display_name": "成员",
                                                "password": "initial8"}, headers=admin_headers)
    assert response.status_code == 201, response.text
    assert response.json()["must_change_password"] is True
    with TestClient(client.app) as member:
        login = member.post("/api/auth/login", json={"username": "member", "password": "initial8"})
        assert login.status_code == 200
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        assert member.get("/api/auth/me").json()["user"]["must_change_password"] is True
        assert member.get("/api/dashboard").status_code == 403
        assert member.get("/api/users").status_code == 403
        assert member.post("/api/auth/change-password", json={"current_password": "wrong",
                           "new_password": "newpass8", "confirm_password": "newpass8"}, headers=headers).status_code == 403
        assert member.post("/api/auth/change-password", json={"current_password": "initial8",
                           "new_password": "initial8", "confirm_password": "initial8"}, headers=headers).status_code == 422
        with TestClient(client.app) as other_device:
            assert other_device.post("/api/auth/login", json={"username": "member", "password": "initial8"}).status_code == 200
            changed = member.post("/api/auth/change-password", json={"current_password": "initial8",
                                  "new_password": "newpass8", "confirm_password": "newpass8"}, headers=headers)
            assert changed.status_code == 204, changed.text
            assert other_device.get("/api/auth/me").status_code == 401
        assert member.get("/api/auth/me").status_code == 401
        assert member.post("/api/auth/login", json={"username": "member", "password": "initial8"}).status_code == 401
        relogin = member.post("/api/auth/login", json={"username": "member", "password": "newpass8"})
        assert relogin.status_code == 200
        assert relogin.json()["user"]["must_change_password"] is False
        assert member.get("/api/dashboard").status_code == 200


def test_admin_edit_reset_disable_and_safe_audit(auth_client):
    client, admin_headers = auth_client
    admin_id = client.get("/api/auth/me").json()["user"]["id"]
    assert client.patch(f"/api/users/{admin_id}", json={"is_active": False}, headers=admin_headers).status_code == 409
    assert client.patch(f"/api/users/{admin_id}", json={"is_admin": False}, headers=admin_headers).status_code == 409
    created = client.post("/api/users", json={"username": "member", "display_name": "成员",
                                                "password": "initial8"}, headers=admin_headers)
    member_id = created.json()["id"]
    with TestClient(client.app) as member:
        login = member.post("/api/auth/login", json={"username": "member", "password": "initial8"})
        assert login.status_code == 200
        edited = client.patch(f"/api/users/{member_id}", json={"display_name": "新姓名", "is_admin": True},
                              headers=admin_headers)
        assert edited.status_code == 200
        assert edited.json()["display_name"] == "新姓名"
        assert edited.json()["is_admin"] is True
        assert client.post(f"/api/users/{admin_id}/reset-password", json={"password": "resetpass8"},
                           headers=admin_headers).status_code == 409
        reset = client.post(f"/api/users/{member_id}/reset-password", json={"password": "resetpass8"},
                            headers=admin_headers)
        assert reset.status_code == 200
        assert reset.json()["must_change_password"] is True
        assert member.get("/api/auth/me").status_code == 401
        assert member.post("/api/auth/login", json={"username": "member", "password": "initial8"}).status_code == 401
        assert member.post("/api/auth/login", json={"username": "member", "password": "resetpass8"}).status_code == 200
        assert client.patch(f"/api/users/{member_id}", json={"is_active": False}, headers=admin_headers).status_code == 200
        assert member.get("/api/auth/me").status_code == 401
        assert member.post("/api/auth/login", json={"username": "member", "password": "resetpass8"}).status_code == 401
        assert client.patch(f"/api/users/{member_id}", json={"is_active": True, "is_admin": False},
                            headers=admin_headers).status_code == 200
        assert member.post("/api/auth/login", json={"username": "member", "password": "resetpass8"}).status_code == 200
        assert member.get("/api/users").status_code == 403
    audits = client.get("/api/audit-logs", params={"page_size": 100}).json()["items"]
    assert all(secret not in str((row["before"], row["after"])) for row in audits
               for secret in ("initial8", "resetpass8", "password_hash"))


def test_password_boundaries_and_non_admin_cannot_manage_users(auth_client):
    client, headers = auth_client
    assert client.post("/api/users", json={"username": "short", "display_name": "短密码",
                                            "password": "1234567"}, headers=headers).status_code == 422
    assert client.post("/api/users", json={"username": "long", "display_name": "长密码",
                                            "password": "x" * 129}, headers=headers).status_code == 422
    response = client.post("/api/users", json={"username": "member", "display_name": "成员",
                                                "password": "12345678"}, headers=headers)
    assert response.status_code == 201
    with TestClient(client.app) as member:
        assert member.post("/api/auth/login", json={"username": "member", "password": "12345678"}).status_code == 200
        assert member.get("/api/users").status_code == 403
        assert member.post("/api/users", json={"username": "another", "display_name": "其他人",
                                               "password": "12345678"}).status_code == 403


def test_migration_round_trip_preserves_users_and_sessions(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    monkeypatch.setenv("SEEDLAB_DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(config, "f705a6bb943c")
    engine = make_engine(url)
    user_id, session_id = str(uuid4()), str(uuid4())
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, created_at, username, display_name, password_hash, is_admin, is_active) "
                                "VALUES (:id, '2026-09-01', 'legacy', '历史用户', 'hashed', 1, 1)"), {"id": user_id})
        connection.execute(text("INSERT INTO sessions (id, created_at, user_id, token_hash, csrf_token, expires_at) "
                                "VALUES (:id, '2026-09-01', :user, :hash, 'csrf', '2027-01-01')"),
                           {"id": session_id, "user": user_id, "hash": "x" * 64})
    engine.dispose()
    command.upgrade(config, "head")
    engine = make_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT must_change_password FROM users WHERE id=:id"), {"id": user_id}).scalar() == 0
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()
    command.downgrade(config, "f705a6bb943c")
    command.upgrade(config, "head")
    engine = make_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "c6d91f28a405"
        assert connection.execute(text("SELECT COUNT(*) FROM sessions WHERE user_id=:id"), {"id": user_id}).scalar() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()
    get_settings.cache_clear()
