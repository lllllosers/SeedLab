"""One product identity for Windows shell, windows, tray and notifications."""
import logging
import os
from pathlib import Path

from PySide6.QtGui import QIcon

PRODUCT_TITLE = "SeedLab 运行控制中心"
APP_ID = "SeedLab.ControlCenter"
ICON_PATH = Path(__file__).parent / "assets/SeedLab.ico"


def product_icon():
    return QIcon(str(ICON_PATH))


class WindowsBrand:
    def set_process_id(self):
        import ctypes
        function = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        function.argtypes = [ctypes.c_wchar_p]
        function.restype = ctypes.c_long
        if function(APP_ID) != 0:
            raise OSError("Windows application identity failed")

    def register_display(self):
        import winreg
        # Only our own product identity, never the Run key or other products.
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                rf"Software\Classes\AppUserModelId\{APP_ID}", 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, PRODUCT_TITLE)
            winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(ICON_PATH.with_suffix(".png").resolve()))


def configure_windows_brand(paths, adapter=None):
    if os.name != "nt" and adapter is None:
        return
    adapter = adapter or WindowsBrand()
    try:
        adapter.set_process_id()  # Before QApplication or any window is created.
        if paths.layout == "portable":
            adapter.register_display()
    except OSError:
        logging.getLogger("seedlab.brand").warning("Windows 产品显示信息设置未完成", exc_info=True)
