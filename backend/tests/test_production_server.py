from pathlib import Path
import importlib.util
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app.core.config import ROOT, Settings, get_settings
from app.main import create_app


@pytest.fixture
def web_root(tmp_path):
    root = tmp_path / "web"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>SeedLab production test</html>", encoding="utf-8")
    (root / "assets" / "test.js").write_text("console.log('static test');", encoding="utf-8")
    return root


@pytest.fixture
def production_settings(client, web_root):
    return get_settings().model_copy(update={"seedlab_env": "production", "seedlab_web_root": web_root})


def test_production_pages_and_api(production_settings):
    # client supplies a migrated isolated database; never start against real data.
    application = create_app(production_settings)
    with TestClient(application) as production:
        for path in ("/", "/login", "/setup", "/change-password", "/taxa", "/taxa/example",
                     "/seed-lots", "/experiments", "/experiments/new", "/experiments/example",
                     "/experiments/example/germination", "/data", "/audit", "/users",
                     "/analysis", "/analysis/species/001", "/some-future-page", "/unknown-page"):
            response = production.get(path)
            assert response.status_code == 200, path
            assert response.text == "<html>SeedLab production test</html>"
            head = production.head(path)
            assert head.status_code == 200
            assert head.content == b""
        health = production.get("/api/health")
        assert health.json() == {"status": "ok", "version": "0.4.0"}
        assert health.headers["content-type"].startswith("application/json")
        for path in ("/api", "/api/nonexistent", "/api/%2e%2e/login", "/docs", "/openapi.json",
                     "/assets/nonexistent.js", "/assets/missing", "/assets", "/missing.css",
                     "/file.xlsx", "/favicon.ico", "/app.js", "/image.png", "/experiments/not-a-page.js"):
            response = production.get(path)
            assert response.status_code == 404, path
            assert "SeedLab production test" not in response.text
        assert production.get("/api/nonexistent").headers["content-type"].startswith("application/json")
        asset = production.get("/assets/test.js")
        assert asset.status_code == 200
        assert asset.text == "console.log('static test');"


def test_static_files_cannot_escape_root(production_settings, web_root):
    (web_root.parent / "secret.txt").write_text("private outside root", encoding="utf-8")
    (web_root.parent / "secret").write_text("private outside root", encoding="utf-8")
    application = create_app(production_settings)
    with TestClient(application) as production:
        for path in ("/assets/%2e%2e/%2e%2e/secret.txt", "/%2e%2e/secret.txt",
                     "/assets/..%5c..%5csecret.txt", "/%2e%2e/secret",
                     "/assets/%2e%2e/%2e%2e/secret", "/..%5csecret", "/%2e/login"):
            response = production.get(path)
            assert response.status_code == 404
            assert "private outside root" not in response.text


def test_outside_root_link_is_not_a_page(production_settings, web_root):
    outside = web_root.parent / "private-directory"
    outside.mkdir()
    (outside / "secret").write_text("outside-root secret", encoding="utf-8")
    link = web_root / "escaped"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        # Windows junctions exercise real link resolution without requiring
        # administrator privileges to create a symbolic link.
        import _winapi
        _winapi.CreateJunction(str(outside), str(link))
    with TestClient(create_app(production_settings)) as production:
        for path in ("/escaped", "/escaped/secret", "/escaped/missing"):
            response = production.get(path)
            assert response.status_code == 404
            assert "outside-root secret" not in response.text
            assert "SeedLab production test" not in response.text


@pytest.mark.parametrize("environment", ["development", "production"])
def test_explicit_settings_control_lifespan(client, tmp_path, web_root, monkeypatch, environment):
    import app.main as main_module
    import app.core.bootstrap as bootstrap_module
    from sqlalchemy import text
    from app.db.session import make_engine

    # The client fixture migrated this isolated database. Clear its test user
    # so startup must create a token using the explicitly provided settings.
    url = get_settings().seedlab_database_url
    engine = make_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM users"))
    engine.dispose()
    token_file = tmp_path / "explicit-bootstrap.token"
    settings = Settings(seedlab_env=environment, seedlab_database_url=url,
                        seedlab_bootstrap_token_path=str(token_file), seedlab_web_root=web_root)

    def unexpected_global_settings():
        pytest.fail("Explicit app settings must also control lifespan initialization")

    urls = []
    def guarded_engine(database_url):
        assert database_url == settings.seedlab_database_url
        urls.append(database_url)
        return make_engine(database_url)

    monkeypatch.setattr(main_module, "get_settings", unexpected_global_settings)
    monkeypatch.setattr(bootstrap_module, "get_settings", unexpected_global_settings)
    monkeypatch.setattr(main_module, "make_engine", guarded_engine)
    application = create_app(settings)
    with TestClient(application) as isolated:
        assert isolated.get("/api/health").status_code == 200
        assert token_file.read_text(encoding="utf-8").strip()
    assert urls == [url]


def test_production_requires_index_and_development_does_not(production_settings, tmp_path):
    missing_root = tmp_path / "no-build"
    with pytest.raises(RuntimeError, match="前端生产文件缺失"):
        create_app(production_settings.model_copy(update={"seedlab_web_root": missing_root}))
    application = create_app(production_settings.model_copy(update={"seedlab_env": "development", "seedlab_web_root": missing_root}))
    with TestClient(application) as development:
        assert development.get("/api/health").status_code == 200
        assert development.get("/docs").status_code == 200


def test_web_root_resolution_is_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert Settings(seedlab_web_root=Path("frontend/dist")).web_root == (ROOT / "frontend/dist").resolve()
    assert Settings(seedlab_web_root=tmp_path).web_root == tmp_path.resolve()


@pytest.fixture
def runner(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setenv("SEEDLAB_ENV", "development")
    monkeypatch.setenv("SEEDLAB_WEB_ROOT", "frontend/dist")
    spec = importlib.util.spec_from_file_location("seedlab_run_prod", ROOT / "scripts/run_prod.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    get_settings.cache_clear()


def test_runner_checks_frontend_before_migrating(runner, tmp_path, monkeypatch, capsys):
    import app.server_entry as entry
    monkeypatch.setattr(runner, "PYTHON", Path(sys.executable))
    def unexpected_migration(*args, **kwargs):
        pytest.fail("Missing frontend must not migrate the database")
    monkeypatch.setattr(entry, "upgrade_database", unexpected_migration)
    assert runner.main(["--web-root", str(tmp_path)]) == 1
    assert "前端生产文件缺失" in capsys.readouterr().out


def test_runner_migration_failure_blocks_server(runner, web_root, monkeypatch, capsys):
    import app.server_entry as entry
    import uvicorn
    monkeypatch.setattr(runner, "PYTHON", Path(sys.executable))
    monkeypatch.setattr(entry, "upgrade_database", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("isolated migration failure")))
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: pytest.fail("Migration failed; server must not start"))
    monkeypatch.chdir(ROOT)  # Restores cwd after runner changes it.
    assert runner.main(["--web-root", str(web_root), "--database", str(web_root.parent / "failed.db")]) == 1
    assert "数据库升级失败" in capsys.readouterr().out


def test_runner_defaults_and_explicit_lan_host(runner):
    defaults = runner.parse_args([])
    assert (defaults.host, defaults.port) == ("127.0.0.1", 8848)
    assert runner.parse_args(["--host", "0.0.0.0"]).host == "0.0.0.0"
    with pytest.raises(SystemExit):
        runner.parse_args(["--port", "0"])
