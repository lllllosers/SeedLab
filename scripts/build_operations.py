"""Build new offline operations artifacts. Never rebuild a frozen distribution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.version import VERSION
from production_ops.deployment import ordinary
from production_ops.package import inspect_package


def owned_directory(path):
    path = ordinary(path).resolve()
    if not any(path.is_relative_to(ROOT / parent) for parent in ("build", "dist")):
        raise ValueError("Build directory must be inside the repository build/dist")
    marker = path / ".seedlab-operations-owned"
    if path.exists():
        if not marker.is_file():
            raise ValueError("Existing unowned output preserved")
        for item in path.rglob("*"):
            ordinary(item)
            if (item.name in {"seedlab.json", "installation.json", "instance.json", "bootstrap.token"}
                    or item.suffix.lower() in {".db", ".sqlite", ".sqlite3"}):
                raise ValueError("Runtime data found in build output; preserved")
        shutil.rmtree(path)
    path.mkdir(parents=True)
    marker.write_text("SeedLab regenerable operations build output\n", encoding="utf-8")


def create_package(program, target, sources):
    build = json.loads((program / "app/build-info.json").read_text(encoding="utf-8"))
    if build["application_version"] != VERSION:
        raise ValueError("Portable version differs from source version")
    manifest = {"format_version": 1, "target_application_version": VERSION, "supported_source_versions": sources,
                "target_alembic_revision": build["alembic_revision"], "build_identity": build["build_identity"],
                "updater_protocol": 1, "migration": "same-schema"}
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for file in sorted(program.rglob("*")):
            ordinary(file)
            if file.is_file():
                archive.write(file, "payload/SeedLab/" + file.relative_to(program).as_posix())
    inspect_package(target, sources[0])
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--portable", type=Path, default=ROOT / "dist/portable-v060/SeedLab")
    parser.add_argument("--output-name", default="operations-v060")
    parser.add_argument("--source-version", action="append")
    args = parser.parse_args()
    if not re.fullmatch(r"operations-[a-z0-9-]+", args.output_name):
        parser.error("Use a new operations-* output name")
    portable = ordinary(args.portable).resolve()
    if not portable.is_relative_to(ROOT / "dist") or portable.is_relative_to(ROOT / "dist/portable-v051"):
        parser.error("Use a new v0.6.0 portable, never the frozen v0.5.1 directory")
    output = ROOT / "dist" / args.output_name
    work = ROOT / "build" / args.output_name
    owned_directory(output)
    owned_directory(work)
    sources = args.source_version or ["0.5.1"]
    package = output / f"SeedLab-v{VERSION}-upgrade.zip"
    manifest = create_package(portable, package, sources)
    tools = output / "tools"
    tools.mkdir()
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", SEEDLAB_OPERATIONS_RESOURCES=str(output))
    python = ROOT / ".venv/Scripts/python.exe"
    for kind in ("launcher", "updater", "bootstrap"):
        environment["SEEDLAB_OPERATIONS_KIND"] = kind
        subprocess.run([str(python), "-B", "-m", "PyInstaller", "--noconfirm", "--workpath", str(work / kind),
                        "--distpath", str(output if kind == "bootstrap" else tools), str(ROOT / "packaging/operations.spec")],
                       env=environment, cwd=ROOT, check=True)
    with package.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    report = {"application_version": VERSION, "manifest": manifest, "upgrade_zip_sha256": digest,
              "artifacts": [{"name": str(file.relative_to(output)), "bytes": file.stat().st_size}
                            for file in [package, *tools.glob("*.exe"), output / f"SeedLab-v{VERSION}-Upgrade.exe"]]}
    (output / "artifact-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
