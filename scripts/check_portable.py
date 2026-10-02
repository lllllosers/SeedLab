"""Read-only candidate directory/ZIP gate. Never inspect or change user data."""
import argparse
import json
from pathlib import Path, PurePosixPath
import zipfile


FORBIDDEN_DIRS = {".git", ".github", ".venv", "node_modules", "tests", "__pycache__", ".pytest_cache",
                  "backups", "data", "coverage", "frontend", "backend"}
FORBIDDEN_FILES = {"bootstrap.token", "seedlab.json", "installation.json", "instance.json", ".env", "browser-input.json"}
REQUIRED = {"SeedLab Control Center.exe", "SeedLabServer.exe", "app/web/index.html", "app/migrations/env.py", "LICENSE", "AUTHORS.md", "使用说明.txt"}


def forbidden(name):
    path = PurePosixPath(name.replace("\\", "/"))
    parts = tuple(part.casefold() for part in path.parts)
    return (any(part in FORBIDDEN_DIRS for part in parts) or path.name.casefold() in FORBIDDEN_FILES
            or path.name.casefold().endswith((".db", ".db-wal", ".db-shm", ".db-journal", ".log", ".pyc"))
            or path.is_absolute() or ".." in parts)


def check_names(names):
    blocked = [name for name in names if forbidden(name)]
    missing = sorted(REQUIRED - set(names))
    if blocked or missing:
        raise ValueError(f"Portable gate failed; forbidden={blocked}; missing={missing}")


def inspect_directory(directory):
    files = list(directory.rglob("*"))
    for file in files:
        if file.is_symlink() or file.lstat().st_file_attributes & 0x400:
            raise ValueError(f"Redirected artifact refused: {file}")
    sizes = {file.relative_to(directory).as_posix():file.stat().st_size for file in files if file.is_file()}
    check_names([file.relative_to(directory).as_posix() for file in files])
    return {"bytes":sum(sizes.values()), "files":len(sizes),
            "largest20":sorted(sizes.items(), key=lambda item:item[1], reverse=True)[:20]}


def inspect_zip(path):
    with zipfile.ZipFile(path) as archive:
        entries = [info.filename for info in archive.infolist()]
        names = [info.filename for info in archive.infolist() if not info.is_dir()]
        if any(not name.startswith("SeedLab/") for name in entries):
            raise ValueError("ZIP must contain exactly one SeedLab root")
        check_names([name.removeprefix("SeedLab/") for name in entries])
        bad = archive.testzip()
        if bad: raise ValueError(f"ZIP CRC failed: {bad}")
    return {"bytes":path.stat().st_size, "files":len(names), "forbidden_files":0}


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--directory",type=Path,required=True)
    parser.add_argument("--zip",type=Path)
    parser.add_argument("--report",type=Path)
    args=parser.parse_args()
    report={"directory":inspect_directory(args.directory)}
    if args.zip: report["zip"]=inspect_zip(args.zip)
    if args.report: args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
