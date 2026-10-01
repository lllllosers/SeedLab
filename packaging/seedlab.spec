# Two onedir executables in one COLLECT: DLLs/data are shared in _internal.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

root = Path(SPECPATH).parent
backend = root / "backend"
hidden = ["app.main", "sqlalchemy.dialects.sqlite", "_cffi_backend", "PySide6.QtSvg"]
hidden += collect_submodules("app.models")
hidden += collect_submodules("uvicorn")
data = collect_data_files("tzdata") + collect_data_files("pypinyin")
assets = [(str(file), "control_center/assets") for file in (root / "control_center/assets").glob("*.svg")]
exclude = ["pytest", "_pytest", "numpy", "pandas", "matplotlib", "tkinter", "IPython", "PyQt5", "PyQt6", "PySide2"]
center = Analysis([str(root / "packaging/control_center_entry.py")], pathex=[str(root), str(backend)],
                  binaries=[], datas=data + assets, hiddenimports=hidden, excludes=exclude)
server = Analysis([str(root / "packaging/server_entry.py")], pathex=[str(backend)],
                  binaries=[], datas=data, hiddenimports=[name for name in hidden if not name.startswith("PySide6")],
                  excludes=exclude + ["PySide6"])
center_pyz = PYZ(center.pure)
server_pyz = PYZ(server.pure)
options = [("X utf8", None, "OPTION"), ("u", None, "OPTION")]
center_exe = EXE(center_pyz, center.scripts, options, exclude_binaries=True,
                 name="SeedLab Control Center", console=False, debug=False, strip=False, upx=False,
                 contents_directory="_internal")
server_exe = EXE(server_pyz, server.scripts, options, exclude_binaries=True,
                 name="SeedLabServer", console=True, debug=False, strip=False, upx=False,
                 contents_directory="_internal")
COLLECT(center_exe, server_exe, center.binaries, server.binaries, center.datas, server.datas,
        name="SeedLab", strip=False, upx=False)
