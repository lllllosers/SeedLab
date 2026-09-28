"""Start the two development servers in one terminal."""
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
NPM = "npm.cmd" if sys.platform == "win32" else "npm"


def main() -> int:
    if not PYTHON.exists():
        print("Backend dependencies missing. Create .venv and install ./backend[test].")
        return 1
    if not (ROOT / "frontend" / "node_modules").exists():
        print("Frontend dependencies missing. Run: cd frontend && npm install")
        return 1
    migration = subprocess.run([str(PYTHON), "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend", check=False)
    if migration.returncode:
        print("Database migration failed; servers were not started.")
        return migration.returncode
    print("SeedLab development servers starting...", flush=True)
    print("Frontend: http://localhost:5173", flush=True)
    print("API docs: http://localhost:8000/docs", flush=True)
    api = subprocess.Popen([str(PYTHON), "-m", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"], cwd=ROOT / "backend")
    web = subprocess.Popen([NPM, "run", "dev"], cwd=ROOT / "frontend")
    try:
        while api.poll() is None and web.poll() is None:
            time.sleep(0.5)
        print("One server exited; stopping the other server.")
        return api.returncode or web.returncode or 1
    except KeyboardInterrupt:
        print("Stopping SeedLab...")
        return 0
    finally:
        for process in (api, web):
            if process.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                else:
                    process.terminate()
        for process in (api, web):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
