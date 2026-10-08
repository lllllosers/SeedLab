"""Adopt a frozen 0.5.1 deployment without moving its Data Root or duplicating its App."""
import os
from pathlib import Path
import shutil
import sys
import tempfile

from . import OperationsError
from .database import inspect
from .deployment import CENTER, SERVER, LAUNCHER, UPDATER, DeploymentStore, absolute, ordinary, read_json, separate
from .windows import executable_version, process_programs


def discover():
    candidates = {path for _, path in process_programs() if path.name == CENTER}
    here = Path(sys.executable).parent
    for path in (here / CENTER, here / "SeedLab" / CENTER):
        if path.is_file():
            candidates.add(path.resolve())
    if os.name == "nt":
        from control_center.startup import RegistryAdapter
        saved = RegistryAdapter().read()
        if saved and saved.startswith('"'):
            path = Path(saved.split('"', 2)[1])
            if path.name == CENTER and path.is_file():
                candidates.add(path.resolve())
    return sorted(candidates)


def inspect_legacy(executable, *, version_reader=executable_version):
    executable = absolute(executable)
    program = executable.parent
    if executable.name != CENTER or any(not (program / name).is_file() for name in (CENTER, SERVER)):
        raise OperationsError("请选择原 SeedLab Control Center.exe，程序文件夹须保持完整。")
    if any(version_reader(program / name) != "0.5.1" for name in (CENTER, SERVER)):
        raise OperationsError("首次升级助手仅支持正式 v0.5.1，请选择对应程序。")
    locator = read_json(program / "config/installation.json")
    if not isinstance(locator, dict) or set(locator) != {"schema_version", "data_root"} or locator["schema_version"] != 1:
        raise OperationsError("原部署的数据位置记录不完整，请从原控制中心检查。")
    data = absolute(locator["data_root"])
    separate(data, program)
    plan = inspect(data, program / "app/migrations")
    if plan.state != "current":
        raise OperationsError("原程序与实验数据库不匹配，首次升级已停止。")
    slot = {"version": "0.5.1", "program_root": str(program), "build_identity": "frozen-v0.5.1",
            "revision": plan.target_revision}
    standard = program.name == "SeedLab" and program.parent.name == "v0.5.1" and program.parent.parent.name == "App"
    root = program.parents[2] if standard else program.parent / "SeedLabManaged"
    return slot, data, root


def adopt(executable, root, tools, *, version_reader=executable_version):
    slot, data, _ = inspect_legacy(executable, version_reader=version_reader)
    store = DeploymentStore(root)
    if store.root == data or store.root.is_relative_to(data):
        raise OperationsError("升级程序目录不能放在实验数据目录内。")
    separate(data, store.root / "App")
    if store.root == Path(slot["program_root"]) or store.root.is_relative_to(Path(slot["program_root"])):
        raise OperationsError("请选择原程序文件夹以外的位置保存升级入口。")
    existing = None
    if store.path.exists():
        existing = store.load()
        if existing["data_root"] != str(data) or existing["current"]["program_root"] != slot["program_root"]:
            raise OperationsError("此位置已属于另一份部署，请选择其他程序根目录。")
    for name in (LAUNCHER, UPDATER):
        if not ordinary(Path(tools) / name).is_file() or (existing is None and ordinary(store.root / name).exists()):
            raise OperationsError("独立升级程序缺失或目标位置已有同名文件，请选择完整升级助手及合适目录。")
    with store.lock():
        state = existing or store.create(slot, data)
        for name in ("Updates", "Logs", "App"):
            ordinary(store.root / name).mkdir(parents=True, exist_ok=True)
        for name in (LAUNCHER, UPDATER):
            target = ordinary(store.root / name)
            if target.is_file():
                continue  # Resume an adoption interrupted between installing the two independent tools.
            temporary = None
            try:
                with (Path(tools) / name).open("rb") as source, tempfile.NamedTemporaryFile(dir=store.root, delete=False) as destination:
                    temporary = Path(destination.name)
                    shutil.copyfileobj(source, destination)
                    destination.flush()
                    os.fsync(destination.fileno())
                temporary.rename(target)
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
        standard = store.root / "App/v0.5.1/SeedLab"
        if Path(slot["program_root"]) == standard:
            (standard.parent / ".seedlab-managed-slot").write_text("SeedLab managed App slot\n", encoding="utf-8")
        return state
