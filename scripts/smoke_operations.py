"""Exercise the built tools and real App processes only in a disposable OS-temp deployment."""
import argparse
from contextlib import closing
import json
import logging
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/tests")]
from sqlalchemy.orm import Session
from app.core.auth import hash_password
from app.db.session import make_engine
from app.models import User
from app.services.migrations import upgrade_database
from app.services.runtime_identity import deployment_identity
from control_center.config_store import ConfigStore, DeploymentSettings
from production_ops.bootstrap import adopt
from production_ops.deployment import CENTER, SERVER, LAUNCHER, UPDATER, DeploymentStore, atomic_json, ordinary
from production_ops.executor import UpgradeExecutor
from production_ops.launcher import launch_command
from production_ops.runtime import CandidateRuntime
from production_ops.windows import require_stopped
from test_production_operations import populate_business, business_rows


def wait_health(port, process, version):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Isolated Server exited before health")
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                payload = json.load(response)
            if payload.get("version") == version and payload.get("status") == "ok":
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise RuntimeError("Isolated Server health timeout")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, default=ROOT / "dist/operations-v060")
    args = parser.parse_args()
    artifacts = ordinary(args.artifacts).resolve()
    if not artifacts.is_relative_to(ROOT / "dist") or not (artifacts / ".seedlab-operations-owned").is_file():
        parser.error("Use this repository's new owned operations build output")
    temporary = ordinary(Path(tempfile.mkdtemp(prefix="seedlab-ops-smoke-"))).resolve()
    root, data = temporary / "Managed Root", temporary / "External Research Data"
    old = root / "App/v0.5.1/SeedLab"
    stop = temporary / "old-server.stop"
    old_process, old_output, runtime = None, None, None
    successful = False
    print(f"Isolated smoke directory: {temporary}", flush=True)
    try:
        shutil.copytree(ROOT / "dist/portable-v051/SeedLab", old)
        database = data / "data/seedlab.db"
        database.parent.mkdir(parents=True)
        upgrade_database("sqlite:///" + database.as_posix(), ROOT / "backend/alembic")
        populate_business(database)
        engine = make_engine("sqlite:///" + database.as_posix())
        with Session(engine) as session, session.begin():
            session.add(User(username="isolated-admin", display_name="隔离验收管理员", is_admin=True,
                             password_hash=hash_password("isolated-build-test-123")))
        engine.dispose()
        with closing(socket.socket()) as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        ConfigStore(data / "config/seedlab.json").save(DeploymentSettings(port=port, auto_backup_enabled=False))
        deployment_identity(data)
        atomic_json(old / "config/installation.json", {"schema_version": 1, "data_root": str(data)})
        before = business_rows(database)
        with closing(sqlite3.connect(database)) as connection:
            accounts = connection.execute("SELECT * FROM users ORDER BY id").fetchall()
        for file in (artifacts / "tools" / LAUNCHER, artifacts / "tools" / UPDATER,
                     artifacts / "SeedLab-v0.6.0-Upgrade.exe"):
            subprocess.run([str(file), "--help"], cwd=temporary, check=True, timeout=90,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        adopt(old / CENTER, root, artifacts / "tools")
        store = DeploymentStore(root)
        runtime = CandidateRuntime(store, isolated=True, timeout=60)
        core = UpgradeExecutor(root, runtime=runtime, progress=lambda text: print(text, flush=True))
        old_output = (temporary / "old-server.log").open("ab")
        command = [str(old / SERVER), "--host", "127.0.0.1", "--port", str(port),
                   "--data-root", str(data), "--database", str(database),
                   "--bootstrap-token", str(data / "data/bootstrap.token"), "--web-root", str(old / "app/web"),
                   "--migration-root", str(old / "app/migrations"), "--access-mode", "local", "--stop-file", str(stop)]
        old_process = subprocess.Popen(command, cwd=old, stdout=old_output, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        wait_health(port, old_process, "0.5.1")
        core.stage(artifacts / "SeedLab-v0.6.0-upgrade.zip")
        wait_health(port, old_process, "0.5.1")  # Staging really leaves the old service running.
        stop.touch()
        old_process.wait(timeout=30)
        state = core.activate()  # Real frozen v0.6.0 Control Center and its owned Server.
        assert state["current"]["version"] == "0.6.0" and state["previous"]["version"] == "0.5.1"
        assert state["pending"] is None and state["data_root"] == str(data)
        assert len(list((data / "backups/before-upgrade").glob("*.db"))) == 1
        assert business_rows(database) == before
        with closing(sqlite3.connect(database)) as connection:
            assert connection.execute("SELECT * FROM users ORDER BY id").fetchall() == accounts
            assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        current_command = launch_command(root, start_server=True)
        assert current_command[0] == str(root / "App/v0.6.0/SeedLab" / CENTER)
        require_stopped(old, root / "App/v0.6.0/SeedLab")
        state = core.rollback()
        assert state["current"]["version"] == "0.5.1" and business_rows(database) == before
        assert launch_command(root)[0] == str(old / CENTER)
        # The old Server can read the unchanged database after rollback.
        stop.unlink(missing_ok=True)
        old_process = subprocess.Popen(command, cwd=old, stdout=old_output, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
        wait_health(port, old_process, "0.5.1")
        stop.touch()
        old_process.wait(timeout=30)
        assert business_rows(database) == before
        report = {"result": "PASS", "database_source": "synthetic isolated fixture, not a production clone",
                  "versions": "0.5.1 -> 0.6.0 -> 0.5.1", "real_candidate_control_center_and_server": True,
                  "staging_while_old_server_running": True, "before_upgrade_snapshots": 1,
                  "research_facts_and_accounts_unchanged": True, "integrity": "ok", "foreign_keys": "ok",
                  "production_mirror_accessed": False, "windows_entrypoints_modified": False}
        (artifacts / "smoke-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        successful = True
    finally:
        stop.touch(exist_ok=True)
        if old_process is not None and old_process.poll() is None:
            old_process.wait(timeout=30)
        if runtime and runtime.process and runtime.process.poll() is None:
            runtime.stop(store.load())
        if old_output:
            old_output.close()
        logging.shutdown()
        if successful:
            expected = ordinary(Path(tempfile.gettempdir())).resolve()
            if temporary.parent != expected or not temporary.name.startswith("seedlab-ops-smoke-"):
                raise RuntimeError("Refusing cleanup outside the verified smoke temp directory")
            shutil.rmtree(temporary)
        else:
            print(f"Failure evidence preserved in: {temporary}", flush=True)


if __name__ == "__main__":
    main()
