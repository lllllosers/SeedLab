"""Small, atomic deployment state. This module is deliberately standard-library only."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import tempfile

from . import OperationsError

FORMAT_VERSION = 1
LAUNCHER = "SeedLab Launcher.exe"
UPDATER = "SeedLab Updater.exe"
CENTER = "SeedLab Control Center.exe"
SERVER = "SeedLabServer.exe"


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise OperationsError("程序版本信息不完整，请重新取得完整升级包。")
    return tuple(map(int, value.split(".")))


def ordinary(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or (item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & 0x400):
            raise OperationsError("程序或数据位置包含重定向目录，请选择普通文件夹。")
    return path


def absolute(value):
    if not isinstance(value, (str, Path)) or not Path(value).is_absolute():
        raise OperationsError("部署位置不完整，请从原 SeedLab 入口重新选择。")
    return ordinary(value).resolve()


def separate(data, program):
    data, program = absolute(data), absolute(program)
    if data == program or data.is_relative_to(program) or program.is_relative_to(data):
        raise OperationsError("实验数据位置必须与程序文件夹分开，原文件尚未更改。")


def atomic_json(path, value):
    path = ordinary(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".seedlab-", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def read_json(path):
    try:
        return json.loads(ordinary(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise OperationsError("部署信息无法读取，请保留原文件并打开升级助手检查。") from error


def validate_slot(slot):
    if not isinstance(slot, dict) or set(slot) != {"version", "program_root", "build_identity", "revision"}:
        raise OperationsError("程序位置记录不完整，请打开升级助手检查。")
    version(slot["version"])
    absolute(slot["program_root"])
    if not all(isinstance(slot[key], str) and slot[key] for key in ("build_identity", "revision")):
        raise OperationsError("程序身份记录不完整，请打开升级助手检查。")
    return slot


def validate_state(value, root):
    if (not isinstance(value, dict) or type(value.get("format_version")) is not int
            or value["format_version"] != FORMAT_VERSION
            or set(value) != {"format_version", "current", "previous", "data_root", "pending", "rollback_snapshot"}):
        raise OperationsError("部署信息版本不受支持，请使用匹配的升级助手。")
    root, data = absolute(root), absolute(value["data_root"])
    if root == data or root.is_relative_to(data):
        raise OperationsError("部署根目录不能放在实验数据目录中。")
    for directory in ("App", "Updates", "Logs", "state"):
        separate(data, root / directory)
    for slot in (value["current"], value["previous"]):
        if slot is not None:
            validate_slot(slot)
            separate(data, slot["program_root"])
    if value["current"] is None:
        raise OperationsError("尚未记录可用的 SeedLab 程序，请打开升级助手。")
    pending = value["pending"]
    if pending is not None:
        if (not isinstance(pending, dict) or not re.fullmatch(r"[0-9a-f]{32}", str(pending.get("id", "")))
                or pending.get("phase") not in {"staged", "maintenance", "protected", "candidate", "failed"}):
            raise OperationsError("上次升级信息无法识别，请保留文件并联系维护人员。")
        validate_slot(pending.get("target"))
        expected = root / "App" / ("v" + pending["target"]["version"]) / "SeedLab"
        if absolute(pending["target"]["program_root"]) != expected:
            raise OperationsError("新程序位置不属于本次部署，升级已停止。")
        separate(data, expected)
    return value


class DeploymentStore:
    def __init__(self, root):
        self.root = absolute(root)
        self.path = self.root / "state/deployment.json"

    def load(self):
        return validate_state(read_json(self.path), self.root)

    def save(self, state):
        atomic_json(self.path, validate_state(state, self.root))

    def create(self, slot, data_root):
        if self.path.exists():
            raise OperationsError("该位置已有部署记录，请打开现有升级助手，避免重复部署。")
        state = {"format_version": FORMAT_VERSION, "current": slot, "previous": None,
                 "data_root": str(absolute(data_root)), "pending": None, "rollback_snapshot": None}
        self.save(state)
        return state

    def job(self, pending):
        return ordinary(self.root / "Updates" / pending["id"])

    @contextmanager
    def lock(self):
        path = ordinary(self.root / "state/operations.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as handle:
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise OperationsError("另一项升级操作尚未结束，请等待完成后重试。") from error
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
