"""Stable, short-lived launcher: no Qt, database, archive or updater imports."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

from . import OperationsError
from .deployment import CENTER, UPDATER, DeploymentStore, absolute, ordinary, version


def launch_command(root, *, startup=False, start_server=False):
    store = DeploymentStore(root)
    state = store.load()
    if state["pending"] is not None:
        executable = ordinary(store.root / UPDATER)
        command = [str(executable), "--root", str(store.root)]
    else:
        slot = state["current"]
        executable = ordinary(Path(slot["program_root"]) / CENTER)
        data = absolute(state["data_root"])
        if not (data / "data/seedlab.db").is_file() or not (data / "config/seedlab.json").is_file():
            raise OperationsError("实验数据目录不完整，请检查原磁盘和数据位置；不会建立空数据替代。")
        command = [str(executable), "--data-root", str(data)]
        if version(slot["version"]) >= (0, 6, 0):
            command += ["--deployment-root", str(store.root)]
            if start_server:
                command.append("--start-server")
        if startup:
            command.append("--startup")
    if not executable.is_file():
        raise OperationsError("SeedLab 程序文件缺失，请保留实验数据并打开升级助手检查。")
    return command


def notify(message):
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "SeedLab", 0x10)
    else:
        print(message, file=sys.stderr)


def main(arguments=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(sys.executable).parent)
    parser.add_argument("--startup", action="store_true")
    parser.add_argument("--start-server", action="store_true")
    parser.add_argument("--refresh-tools-only", action="store_true")
    args = parser.parse_args(arguments)
    try:
        from .tool_refresh import finish_refresh, pending_refresh, start_refresh, log_event
        if args.refresh_tools_only:
            return 0 if finish_refresh(args.root) else 1
        try:
            if pending_refresh(args.root):
                # Run from the target App resource, so this root Launcher can exit
                # and itself be replaced without touching its mapped image.
                start_refresh(args.root)
        except (OperationsError, OSError) as error:
            # The current App still opens and displays the incomplete refresh.
            log_event(args.root, 'Tool refresh launch incomplete: ' + repr(error))
        command = launch_command(args.root, startup=args.startup, start_server=args.start_server)
        subprocess.Popen(command, cwd=args.root, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return 0
    except (OperationsError, OSError):
        error = sys.exc_info()[1]
        notify(str(error) if isinstance(error, OperationsError) else "SeedLab 未能打开，请检查程序目录权限并重试。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
