"""One HKCU Run value, with an injectable registry boundary for tests."""
from dataclasses import dataclass
import os

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "SeedLabControlCenter"


class RegistryAdapter:
    def read(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
                value, kind = winreg.QueryValueEx(key, VALUE_NAME)
                return value if kind == winreg.REG_SZ else "unsupported"
        except FileNotFoundError:
            return None

    def write(self, value):
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, value)

    def delete(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class StartupState:
    enabled: bool = False
    stale: bool = False
    warning: str = ""


class StartupManager:
    def __init__(self, paths, registry=None):
        self.paths = paths
        self.available = paths.layout == "portable" and (os.name == "nt" or registry is not None)
        self.registry = registry if registry is not None else RegistryAdapter()

    @property
    def command(self):
        executable = str(self.paths.deployment_root / "SeedLab Launcher.exe" if self.paths.deployment_root else self.paths.control_executable)
        if '"' in executable:
            raise ValueError("程序位置包含不支持的字符，请移动程序文件夹后重试。")
        return f'"{executable}" --startup'

    def state(self):
        if not self.available:
            return StartupState(warning="便携版部署后可设置 Windows 登录启动。")
        try:
            value = self.registry.read()
            enabled = value is not None and value.casefold() == self.command.casefold()
            stale = value is not None and not enabled
            return StartupState(enabled, stale, "开机启动指向旧程序位置，请重新勾选并保存。" if stale else "")
        except OSError:
            return StartupState(warning="无法读取登录启动设置，请检查当前 Windows 用户权限后重试。")

    def save(self, enabled):
        if not self.available:
            raise ValueError("便携版部署后可设置 Windows 登录启动。")
        if enabled:
            executable = self.paths.deployment_root / "SeedLab Launcher.exe" if self.paths.deployment_root else self.paths.control_executable
            if not executable.is_file():
                raise ValueError("程序文件缺失，请检查 SeedLab 文件夹后再设置登录启动。")
            self.registry.write(self.command)
        else:
            self.registry.delete()
