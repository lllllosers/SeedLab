# Two onedir executables in one COLLECT: DLLs/data are shared in _internal.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files
from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct
from app.version import VERSION

root = Path(SPECPATH).parent
backend = root / "backend"
hidden = ["app.main", "sqlalchemy.dialects.sqlite", "_cffi_backend", "PySide6.QtSvg"]
hidden += collect_submodules("app.models")
hidden += collect_submodules("uvicorn")
data = collect_data_files("tzdata") + collect_data_files("pypinyin")
assets = [(str(file), "control_center/assets") for file in (root / "control_center/assets").iterdir()
          if file.suffix in {".svg", ".ico", ".png"}]
icon = str(root / "control_center/assets/SeedLab.ico")
version_tuple = tuple(int(part) for part in VERSION.split(".")) + (0,)
def product_version(description, filename):
    return VSVersionInfo(ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple,
        mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)), kids=[
        StringFileInfo([StringTable("080404b0", [StringStruct("CompanyName", "SeedLab"),
            StringStruct("FileDescription", description), StringStruct("ProductName", "SeedLab"),
            StringStruct("FileVersion", VERSION), StringStruct("ProductVersion", VERSION),
            StringStruct("OriginalFilename", filename)])]),
        VarFileInfo([VarStruct("Translation", [0x804, 1200])])])
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
                 icon=icon, version=product_version("SeedLab 运行控制中心", "SeedLab Control Center.exe"),
                 name="SeedLab Control Center", console=False, debug=False, strip=False, upx=False,
                 contents_directory="_internal")
server_exe = EXE(server_pyz, server.scripts, options, exclude_binaries=True,
                 icon=icon, version=product_version("SeedLab 服务", "SeedLabServer.exe"),
                 name="SeedLabServer", console=True, debug=False, strip=False, upx=False,
                 contents_directory="_internal")
COLLECT(center_exe, server_exe, center.binaries, server.binaries, center.datas, server.datas,
        name="SeedLab", strip=False, upx=False)
