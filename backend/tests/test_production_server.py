from pathlib import Path
import importlib.util
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app.core.config import ROOT, Settings
from app.main import create_app


@pytest.fixture
def web_root(tmp_path):
    root = tmp_path / "web"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>SeedLab production test</html>", encoding="utf-8")
    (root / "assets" / "test.js").write_text("console.log('static test');", encoding="utf-8")
    return root


def test_production_pages_and_api(client, web_root):
    # client supplies a migrated isolated database; never start against real data.
    application = create_app(Settings(seedlab_env="production", seedlab_web_root=web_root))
    with TestClient(application) as production:
        for path in ("/", "/login", "/setup", "/change-password", "/taxa", "/taxa/example",
                     "/seed-lots", "/experiments", "/experiments/new", "/experiments/example",
                     "/experiments/example/germination", "/data", "/audit", "/users"):
            response = production.get(path)
            assert response.status_code == 200, path
            assert response.text == "<html>SeedLab production test</html>"
        health = production.get("/api/health")
        assert health.json() == {"status": "ok", "version": "0.4.0"}
        assert health.headers["content-type"].startswith("application/json")
        for path in ("/api", "/api/nonexistent", "/api/%2e%2e/login", "/docs", "/openapi.json", "/unknown-page",
                     "/assets/nonexistent.js", "/missing.css", "/experiments/not-a-page.js"):
            response = production.get(path)
            assert response.status_code == 404, path
            assert "SeedLab production test" not in response.text
        assert production.get("/api/nonexistent").headers["content-type"].startswith("application/json")
        asset = production.get("/assets/test.js")
        assert asset.status_code == 200
        assert asset.text == "console.log('static test');"


def test_static_files_cannot_escape_root(client, web_root):
    (web_root.parent / "secret.txt").write_text("private outside root", encoding="utf-8")
    application = create_app(Settings(seedlab_env="production", seedlab_web_root=web_root))
    with TestClient(application) as production:
        for path in ("/assets/%2e%2e/%2e%2e/secret.txt", "/%2e%2e/secret.txt",
                     "/assets/..%5c..%5csecret.txt"):
            response = production.get(path)
            assert response.status_code == 404
            assert "private outside root" not in response.text


def test_production_requires_index_and_development_does_not(client, tmp_path):
    missing_root = tmp_path / "no-build"
    with pytest.raises(RuntimeError, match="前端生产文件缺失"):
        create_app(Settings(seedlab_env="production", seedlab_web_root=missing_root))
    application = create_app(Settings(seedlab_env="development", seedlab_web_root=missing_root))
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
    monkeypatch.setattr(runner, "PYTHON", Path(sys.executable))
    def unexpected_migration(*args, **kwargs):
        pytest.fail("Missing frontend must not migrate the database")
    monkeypatch.setattr(runner.subprocess, "run", unexpected_migration)
    assert runner.main(["--web-root", str(tmp_path)]) == 1
    assert "前端生产文件缺失" in capsys.readouterr().out


def test_runner_migration_failure_blocks_server(runner, web_root, monkeypatch, capsys):
    import uvicorn
    monkeypatch.setattr(runner, "PYTHON", Path(sys.executable))
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1))
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: pytest.fail("Migration failed; server must not start"))
    monkeypatch.chdir(ROOT)  # Restores cwd after runner changes it.
    assert runner.main(["--web-root", str(web_root)]) == 1
    assert "数据库升级失败" in capsys.readouterr().out


def test_runner_defaults_and_explicit_lan_host(runner):
    defaults = runner.parse_args([])
    assert (defaults.host, defaults.port) == ("127.0.0.1", 8848)
    assert runner.parse_args(["--host", "0.0.0.0"]).host == "0.0.0.0"
    with pytest.raises(SystemExit):
        runner.parse_args(["--port", "0"])
