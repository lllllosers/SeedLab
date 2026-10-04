"""Source-tree launcher for the Windows control center."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main():
    if not PYTHON.is_file():
        print('请先创建 .venv，再安装：pip install -e "./backend[control]"')
        return 1
    if Path(sys.executable).resolve() != PYTHON.resolve():
        return subprocess.call([str(PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=ROOT)
    sys.path.insert(0, str(ROOT))
    try:
        import PySide6  # noqa: F401
    except ImportError:
        print('控制中心依赖缺失，请安装：pip install -e "./backend[control]"')
        return 1
    try:
        from control_center.app import main as launch
    except ImportError:
        from control_center.log_utils import make_logger
        make_logger(ROOT / "logs", "control-center").exception("控制中心运行库加载失败")
        print('控制中心运行库无法加载，请重新安装：pip install -e "./backend[control]"。详细原因已写入日志。')
        return 1
    return launch()


if __name__ == "__main__":
    raise SystemExit(main())
