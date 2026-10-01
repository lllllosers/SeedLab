"""Single test entry point for Windows and other development systems."""
import subprocess
import sys
from tempfile import TemporaryDirectory
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"


def main() -> int:
    if not PYTHON.exists():
        print("请先创建 .venv 并安装 backend[test] 依赖。")
        return 1
    arguments = sys.argv[1:]
    if any(arg == "--basetemp" or arg.startswith("--basetemp=") for arg in arguments):
        return subprocess.call([str(PYTHON), "-m", "pytest", "-q", *arguments], cwd=ROOT / "backend")
    # An owned system-temp directory avoids both repository pollution and stale
    # pytest-of-user directories with permissions left by earlier Windows runs.
    with TemporaryDirectory(prefix="seedlab-tests-") as test_directory:
        return subprocess.call([str(PYTHON), "-m", "pytest", "-q", "--basetemp", test_directory,
                                *arguments], cwd=ROOT / "backend")


if __name__ == "__main__":
    raise SystemExit(main())
