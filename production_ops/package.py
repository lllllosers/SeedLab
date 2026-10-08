"""A local ZIP contract: CRC, safe paths and build identity, without per-file hashes."""
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile

from . import OperationsError
from .deployment import CENTER, SERVER, ordinary, version

PROTOCOL = 1
REQUIRED = {CENTER, SERVER, "app/web/index.html", "app/migrations/env.py", "app/build-info.json",
            "_internal/python312.dll", "使用说明.txt"}
FORBIDDEN = {"data", "backups", "logs", ".git", ".venv", "node_modules"}
CONFIG_FILES = {"seedlab.json", "installation.json", "instance.json", "bootstrap.token", ".env"}


def manifest_value(value):
    required = {"format_version", "target_application_version", "supported_source_versions",
                "target_alembic_revision", "build_identity", "updater_protocol", "migration"}
    if not isinstance(value, dict) or set(value) != required:
        raise OperationsError("升级包说明不完整，请重新取得完整升级包。")
    if (type(value["format_version"]) is not int or value["format_version"] != 1
            or type(value["updater_protocol"]) is not int or value["updater_protocol"] != PROTOCOL):
        raise OperationsError("升级包需要其他版本的升级助手，请联系维护人员。")
    version(value["target_application_version"])
    sources = value["supported_source_versions"]
    if (not isinstance(sources, list) or not sources or not all(isinstance(item, str) for item in sources)
            or len(sources) != len(set(sources))):
        raise OperationsError("升级包未明确支持的旧版本，请重新取得升级包。")
    for source in sources:
        version(source)
    if (not isinstance(value["target_alembic_revision"], str)
            or not re.fullmatch(r"[A-Za-z0-9_]+", value["target_alembic_revision"])
            or not isinstance(value["build_identity"], str) or not value["build_identity"].strip()
            or len(value["build_identity"]) > 200 or value["migration"] not in {"same-schema", "af1"}):
        raise OperationsError("升级包的程序或数据库信息不完整。")
    return value


def check_source(manifest, current):
    if current not in manifest["supported_source_versions"]:
        raise OperationsError("这个升级包不支持当前版本，请选择匹配的升级包。")
    if version(manifest["target_application_version"]) <= version(current):
        raise OperationsError("请选择比当前版本更新的升级包；返回旧版本请使用恢复入口。")


def entry_name(info):
    name = info.filename.replace("\\", "/")
    parts = name.rstrip("/").split("/")
    if (not parts or any(not part or part in {".", ".."} or ":" in part
                         or part.rstrip(" .") != part or re.search(r"[\x00-\x1f]", part)
                         or re.fullmatch(r"(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
                         for part in parts)
            or name.startswith("/") or stat.S_ISLNK(info.external_attr >> 16)):
        raise OperationsError("升级包包含不安全的文件位置，尚未更改当前程序。")
    return "/".join(parts)


def inspect_archive(archive):
    seen, file_names, bytes_total = {}, set(), 0
    for info in archive.infolist():
        name = entry_name(info)
        key = name.casefold()
        if key in seen:
            raise OperationsError("升级包存在重复文件位置，请重新取得完整升级包。")
        seen[key] = info.is_dir()
        if name != "manifest.json" and not (name == "payload" or name.startswith("payload/SeedLab")):
            raise OperationsError("升级包目录结构不受支持。")
        if name.startswith("payload/SeedLab") and name not in {"payload/SeedLab"} and not name.startswith("payload/SeedLab/"):
            raise OperationsError("升级包目录结构不受支持。")
        if name.startswith("payload/SeedLab/"):
            relative = name[len("payload/SeedLab/"):]
            parts = PurePosixPath(relative).parts
            if (any(part.casefold() in FORBIDDEN for part in parts) or parts[-1].casefold() in CONFIG_FILES
                    or parts[-1].casefold().endswith((".db", ".db-wal", ".db-shm", ".db-journal", ".log"))):
                raise OperationsError("升级包混入了运行数据或配置，请重新取得程序包。")
            if not info.is_dir():
                file_names.add(relative)
        bytes_total += info.file_size
        if info.flag_bits & 1 or bytes_total > 4 * 1024 ** 3 or len(seen) > 20000:
            raise OperationsError("升级包加密或大小超出支持范围，请检查所选文件。")
    for name in seen:
        if any(seen.get(str(parent)) is False for parent in PurePosixPath(name).parents if str(parent) != "."):
            raise OperationsError("升级包中的文件夹与文件冲突。")
    if REQUIRED - file_names:
        raise OperationsError("升级包缺少必要程序文件，请重新取得完整升级包。")
    if archive.testzip() is not None:
        raise OperationsError("升级包读取检查未通过，请重新复制或取得升级包。")
    try:
        manifest = manifest_value(json.loads(archive.read("manifest.json")))
        build = json.loads(archive.read("payload/SeedLab/app/build-info.json"))
        expected = {"application_version": manifest["target_application_version"],
                    "alembic_revision": manifest["target_alembic_revision"], "build_identity": manifest["build_identity"]}
        if build != expected:
            raise OperationsError("升级包说明与程序身份不一致，请重新取得完整升级包。")
    except (KeyError, ValueError, TypeError) as error:
        if isinstance(error, OperationsError):
            raise
        raise OperationsError("升级包的版本信息无法读取。") from error
    return manifest, bytes_total


def inspect_package(path, current=None):
    try:
        with zipfile.ZipFile(ordinary(path)) as archive:
            manifest, _ = inspect_archive(archive)
            if current is not None:
                check_source(manifest, current)
            return manifest
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise OperationsError("升级包无法完整读取，请重新选择有效的 ZIP 文件。") from error


def extract_package(path, destination, current):
    destination = ordinary(destination).resolve()
    if destination.exists():
        raise OperationsError("本次准备目录已经存在，请重新开始一次升级。")
    try:
        with zipfile.ZipFile(ordinary(path)) as archive:
            manifest, size = inspect_archive(archive)
            check_source(manifest, current)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(destination.parent).free < size + 64 * 1024 ** 2:
                raise OperationsError("程序磁盘空间不足，请释放空间后重试；当前版本未停止。")
            destination.mkdir()
            for info in archive.infolist():
                name = entry_name(info)
                if not name.startswith("payload/SeedLab/"):
                    continue
                target = ordinary(destination / name[len("payload/SeedLab/"):])
                if not target.is_relative_to(destination):
                    raise OperationsError("升级包文件超出准备目录，升级已停止。")
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
            return manifest
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise OperationsError("新程序准备未完成，当前版本未停止。请检查升级包、磁盘空间和权限。") from error
