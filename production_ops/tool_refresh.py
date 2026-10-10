"""Two-tool deferred replacement. No database access, resident helper or download.

The sidecar deliberately leaves protocol-1 deployment.json readable by frozen
0.6.0 tools until their normal exit. The target App carries the short-lived
Launcher used for promotion; it is not a third installed updater.
"""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import time
from datetime import datetime, timezone

from . import OperationsError
from .deployment import LAUNCHER, UPDATER, DeploymentStore, atomic_json, ordinary, read_json
from .windows import executable_version, process_programs

TOOLS = (LAUNCHER, UPDATER)
MESSAGE = 'SeedLab 已升级，但升级工具更新未完成。请关闭原升级助手，再重试升级工具更新；实验数据不受影响。'


def log_event(root, text):
    path = ordinary(Path(root) / 'Logs/tool-refresh.log')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as output:
            output.write(f'{datetime.now(timezone.utc).isoformat()} {text}\n')
    except OSError:
        pass  # Retained intent and visible notice remain the authority.


def digest(path):
    with ordinary(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def state_path(store):
    return store.root / 'state/tool-refresh.json'


def pending_refresh(root):
    store = DeploymentStore(root)
    path = state_path(store)
    if not path.is_file():
        return None
    state = read_json(path)
    if not isinstance(state, dict) or set(state) != {'tool_refresh_pending'} or not isinstance(state['tool_refresh_pending'], (dict, type(None))):
        raise OperationsError('升级工具状态无法读取，请保留现场并重试升级工具更新。')
    pending = state['tool_refresh_pending']
    if pending is not None and not {'version', 'build_identity', 'program_root'} <= pending.keys():
        raise OperationsError('升级工具状态不完整，请保留现场并重试升级工具更新。')
    return pending


def resources(slot):
    folder = ordinary(Path(slot['program_root']) / 'app/upgrade-tools')
    info = read_json(folder / 'tools.json')
    if (not isinstance(info, dict) or set(info) != {'version', 'build_identity', 'tools'} or info['version'] != slot['version']
            or info['build_identity'] != slot['build_identity'] or not isinstance(info['tools'], dict)
            or set(info['tools']) != set(TOOLS)
            or any(not isinstance(info['tools'][name], str) or not re.fullmatch(r'[0-9a-f]{64}', info['tools'][name]) for name in TOOLS)):
        raise OperationsError('升级工具与目标程序身份不一致，请重新取得完整升级包。')
    return folder, info


def verify(path, name, info, version_reader=executable_version):
    if digest(path) != info['tools'][name] or version_reader(path) != info['version']:
        raise OperationsError('升级工具完整性检查未通过，已保留原入口，请重新取得完整升级包。')


def stage_refresh(root, slot, *, version_reader=executable_version):
    store = DeploymentStore(root)
    with store.lock('tool-refresh.lock'):
        return _stage_refresh(store, slot, version_reader)


def _stage_refresh(store, slot, version_reader):
    atomic_json(state_path(store), {'tool_refresh_pending': {**slot, 'message': MESSAGE}})
    folder, info = resources(slot)
    for name in TOOLS:
        verify(folder / name, name, info, version_reader)
    if all((store.root / name).is_file() and digest(store.root / name) == info['tools'][name] for name in TOOLS):
        atomic_json(state_path(store), {'tool_refresh_pending': None})
        return None
    # Record intent before copying, so interruption or disk failure remains visible.
    pending = {**info, 'program_root': slot['program_root'], 'message': MESSAGE}
    atomic_json(state_path(store), {'tool_refresh_pending': pending})
    for name in TOOLS:
        next_path = ordinary(store.root / name.replace('.exe', '.next.exe'))
        temporary = ordinary(next_path.with_suffix('.tmp'))
        shutil.copyfile(folder / name, temporary)
        verify(temporary, name, info, version_reader)
        os.replace(temporary, next_path)
    log_event(store.root, 'Target tools staged: ' + info['build_identity'])
    return pending


def finish_refresh(root, *, timeout=30, version_reader=executable_version, processes=process_programs):
    store = DeploymentStore(root)
    deadline = time.monotonic() + timeout
    while True:
        try:
            with store.lock(), store.lock('tool-refresh.lock'):
                pending = pending_refresh(root)
                if pending is None:
                    return True
                if not isinstance(pending, dict) or not {'version', 'build_identity', 'program_root', 'tools'} <= pending.keys():
                    raise OperationsError('升级工具准备未完成，请在系统升级页面重试。')
                state = store.load()
                if state['pending'] is not None or any(state['current'][key] != pending[key] for key in ('version', 'build_identity', 'program_root')):
                    return False  # Never promote candidate tools before App commit or during rollback.
                folder, info = resources(state['current'])
                if any(info[key] != pending[key] for key in ('version', 'build_identity', 'tools')):
                    raise OperationsError('升级工具记录与当前程序不一致，请保留现场并查看升级日志。')
                root_tools = {store.root / name for name in TOOLS}
                if any(path in root_tools for _, path in processes(TOOLS)):
                    raise PermissionError('Root tool still running')
                for name in TOOLS:
                    target = ordinary(store.root / name)
                    if target.is_file() and digest(target) == info['tools'][name]:
                        verify(target, name, info, version_reader)
                        continue
                    next_path = ordinary(store.root / name.replace('.exe', '.next.exe'))
                    if not next_path.is_file():
                        shutil.copyfile(folder / name, next_path)
                    verify(next_path, name, info, version_reader)
                    os.replace(next_path, target)
                    verify(target, name, info, version_reader)
                for name in TOOLS:
                    ordinary(store.root / name.replace('.exe', '.next.exe')).unlink(missing_ok=True)
                atomic_json(state_path(store), {'tool_refresh_pending': None})
                log_event(store.root, 'Root tools verified and promoted: ' + info['build_identity'])
                return True
        except (OSError, OperationsError) as error:
            if time.monotonic() >= deadline:
                # Intent is retained even when the state file cannot be rewritten.
                log_event(store.root, 'Tool refresh incomplete: ' + repr(error))
                return False
            time.sleep(0.2)


def start_refresh(root):
    store = DeploymentStore(root)
    slot = store.load()['current']
    folder, _ = resources(slot)
    return subprocess.Popen([str(folder / LAUNCHER), '--root', str(store.root), '--refresh-tools-only'],
                            cwd=store.root, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def updater_command(root):
    root = ordinary(root).resolve()
    if pending_refresh(root):
        raise OperationsError(MESSAGE)
    return [str(root / UPDATER), '--root', str(root)]
