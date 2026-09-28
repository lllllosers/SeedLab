"""Single test entry point for Windows and other development systems."""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    if not PYTHON.exists():
        print("请先创建 .venv 并安装 backend[test] 依赖。")
        return 1
    return subprocess.call([str(PYTHON), "-m", "pytest", "-q", *sys.argv[1:]], cwd=ROOT / "backend")


if __name__ == "__main__":
    raise SystemExit(main())
