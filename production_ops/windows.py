"""Small Windows boundaries: executable identity, owned processes and shell entrypoints."""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess

from . import OperationsError
from .deployment import CENTER, SERVER, LAUNCHER, ordinary


def executable_version(path):
    if os.name != "nt":
        raise OperationsError("便携程序升级需要在 Windows 上运行。")
    library = ctypes.WinDLL("version", use_last_error=True)
    library.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
    library.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    length = library.GetFileVersionInfoSizeW(str(path), None)
    if not length:
        raise OperationsError("无法确认 SeedLab 程序版本，请选择完整的正式程序目录。")
    buffer = ctypes.create_string_buffer(length)
    library.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    library.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    if not library.GetFileVersionInfoW(str(path), 0, length, buffer):
        raise OperationsError("程序版本信息无法读取。")
    pointer, size = ctypes.c_void_p(), wintypes.UINT()
    if not library.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(size)) or size.value < 24:
        raise OperationsError("程序版本信息不完整。")
    fields = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD))
    return f"{fields[2] >> 16}.{fields[2] & 65535}.{fields[3] >> 16}"


def process_programs():
    """Only enumerate the two SeedLab binaries; inaccessible matching processes block maintenance."""
    if os.name != "nt":
        return []
    class Entry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
                    ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                    ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
                    ("name", wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise OperationsError("无法检查运行中的 SeedLab，请关闭相关程序后重试。")
    found = []
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.name.casefold() in {CENTER.casefold(), SERVER.casefold()}:
                handle = kernel.OpenProcess(0x1000, False, entry.pid)
                if not handle:
                    raise OperationsError("发现无法确认归属的 SeedLab 进程，请在原入口退出后重试。")
                try:
                    length = wintypes.DWORD(32768)
                    text = ctypes.create_unicode_buffer(length.value)
                    if not kernel.QueryFullProcessImageNameW(handle, 0, text, ctypes.byref(length)):
                        raise OperationsError("无法确认运行程序的位置，请在原入口退出后重试。")
                    found.append((entry.pid, Path(text.value).resolve()))
                finally:
                    kernel.CloseHandle(handle)
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return found


def require_stopped(*programs):
    targets = {Path(root).resolve() for root in programs}
    if any(path.parent in targets for _, path in process_programs()):
        raise OperationsError("请在原控制中心选择“停止 SeedLab 并退出”，然后重试。关闭窗口只会隐藏到托盘。")


@contextmanager
def closed_program(program):
    require_stopped(program)
    handles = []
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        if os.name == "nt":
            for name in (CENTER, SERVER):
                # No shared reads: the frozen 0.5.1 executables cannot restart during maintenance.
                handle = kernel.CreateFileW(str(ordinary(Path(program) / name)), 0x80000000, 0, None, 3, 0x80, None)
                if handle == ctypes.c_void_p(-1).value:
                    raise OperationsError("旧程序仍被使用或无法独占检查，请完全退出控制中心和服务后重试。")
                handles.append(handle)
        yield
    finally:
        if os.name == "nt":
            for handle in handles:
                kernel.CloseHandle(handle)


def connect_startup(root, old_program):
    """Preserve enabled/disabled intent; never take over another deployment's Run value."""
    from control_center.startup import RegistryAdapter
    registry = RegistryAdapter()
    saved = registry.read()
    old = f'"{Path(old_program) / CENTER}" --startup'
    current = f'"{Path(root) / LAUNCHER}" --startup'
    if saved and saved.casefold() == old.casefold():
        registry.write(current)


def create_shortcut(root, old_program):
    # Windows supplies WScript.Shell. Use stdin and environment variables, never interpolate paths as code.
    environment = dict(os.environ, SEEDLAB_LAUNCHER_PATH=str(Path(root) / LAUNCHER),
                       SEEDLAB_OLD_CENTER=str(Path(old_program) / CENTER), SEEDLAB_DEPLOYMENT_ROOT=str(root))
    script = """$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$path = Join-Path $desktop 'SeedLab.lnk'
$shortcut = $shell.CreateShortcut($path)
if ((Test-Path -LiteralPath $path) -and $shortcut.TargetPath -and
    $shortcut.TargetPath -notin @($env:SEEDLAB_LAUNCHER_PATH, $env:SEEDLAB_OLD_CENTER)) { throw 'Unrelated shortcut preserved' }
$shortcut.TargetPath = $env:SEEDLAB_LAUNCHER_PATH
$shortcut.WorkingDirectory = $env:SEEDLAB_DEPLOYMENT_ROOT
$shortcut.Description = 'SeedLab'
$shortcut.Save()
"""
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "-"],
        input=script, text=True, capture_output=True, env=environment, timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise OperationsError("程序已安装，桌面入口未能创建。请直接打开部署根目录中的 SeedLab Launcher。")
