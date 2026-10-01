"""Source-tree launcher for the shared portable-ready server entry point."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
sys.path.insert(0, str(ROOT / "backend"))


def main(arguments=None):
    actual = sys.argv[1:] if arguments is None else arguments
    explicit_database = "--database" in actual or any(arg.startswith("--database=") for arg in actual)
    if not explicit_database and not PYTHON.is_file():
        print("Python 环境缺失，请先创建 .venv 并安装 backend 依赖。", flush=True)
        return 1
    if not explicit_database and Path(sys.executable).resolve() != PYTHON.resolve():
        with subprocess.Popen([str(PYTHON), str(Path(__file__).resolve()),
                               *(sys.argv[1:] if arguments is None else arguments)], cwd=ROOT) as process:
            try:
                return process.wait()
            except KeyboardInterrupt:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait()
                return 0
    try:
        from app.server_entry import main as launch
    except ImportError:
        print("Python 依赖不完整，请先安装 backend 依赖。", flush=True)
        return 1
    return launch(actual)


# Kept importable for lifecycle callers/tests; actual startup lives in one module.
from app.server_entry import parse_args, watch_stop_file, serve_with_stop_file

if __name__ == "__main__":
    raise SystemExit(main())
