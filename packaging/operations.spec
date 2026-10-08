# Standalone onefile tools; none loads its runtime from an App slot.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct
from app.version import VERSION

root = Path(SPECPATH).parent
kind = os.environ["SEEDLAB_OPERATIONS_KIND"]
names = {"launcher": "SeedLab Launcher", "updater": "SeedLab Updater", "bootstrap": f"SeedLab-v{VERSION}-Upgrade"}
name = names[kind]
datas, hidden = [], []
exclude = ["pytest", "_pytest", "numpy", "pandas", "matplotlib", "tkinter", "IPython", "PyQt5", "PyQt6", "PySide2"]
if kind == "launcher":
    exclude += ["PySide6", "sqlalchemy", "alembic", "fastapi", "uvicorn", "openpyxl", "app", "control_center"]
else:
    hidden = collect_submodules("app.models") + ["sqlalchemy.dialects.sqlite", "_cffi_backend", "PySide6.QtSvg"]
    datas = collect_data_files("tzdata") + collect_data_files("pypinyin")
    datas += [(str(file), "control_center/assets") for file in (root / "control_center/assets").iterdir()
              if file.suffix in {".svg", ".ico", ".png"}]
if kind == "bootstrap":
    resources = Path(os.environ["SEEDLAB_OPERATIONS_RESOURCES"])
    datas += [(str(resources / f"SeedLab-v{VERSION}-upgrade.zip"), "."),
              (str(resources / "tools/SeedLab Launcher.exe"), "tools"),
              (str(resources / "tools/SeedLab Updater.exe"), "tools")]
numeric = tuple(map(int, VERSION.split("."))) + (0,)
version_info = VSVersionInfo(ffi=FixedFileInfo(filevers=numeric, prodvers=numeric, mask=0x3f,
    flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)), kids=[StringFileInfo([StringTable("080404b0", [
    StringStruct("ProductName", "SeedLab"), StringStruct("FileVersion", VERSION),
    StringStruct("ProductVersion", VERSION), StringStruct("FileDescription", name)])])])
analysis = Analysis([str(root / f"packaging/{kind}_entry.py")], pathex=[str(root), str(root / "backend")],
                    binaries=[], datas=datas, hiddenimports=hidden, excludes=exclude)
archive = PYZ(analysis.pure)
EXE(archive, analysis.scripts, analysis.binaries, analysis.datas, [("X utf8", None, "OPTION"), ("u", None, "OPTION")],
    name=name, console=False, debug=False, strip=False, upx=False,
    icon=str(root / "control_center/assets/SeedLab.ico"), version=version_info)
