"""Read-only operations artifact gate, including independence of bundled runtimes."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PyInstaller.archive.readers import CArchiveReader
from app.version import VERSION
from production_ops.package import inspect_package
from production_ops.windows import executable_version


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory
    manifest = inspect_package(directory / f"SeedLab-v{VERSION}-upgrade.zip")
    assert manifest["target_application_version"] == VERSION
    for name in ("SeedLab Launcher.exe", "SeedLab Updater.exe"):
        file = directory / "tools" / name
        assert executable_version(file) == VERSION
        names = set(CArchiveReader(str(file)).toc)
        assert any("python312.dll" in item.lower() for item in names)
        qt = any("pyside6" in item.lower() for item in names)
        assert qt == ("Updater" in name), "Launcher must remain independent of Qt; Updater must carry its own runtime"
    bootstrap = directory / f"SeedLab-v{VERSION}-Upgrade.exe"
    assert executable_version(bootstrap) == VERSION
    names = {item.replace("\\", "/") for item in CArchiveReader(str(bootstrap)).toc}
    assert {f"SeedLab-v{VERSION}-upgrade.zip", "tools/SeedLab Launcher.exe", "tools/SeedLab Updater.exe"} <= names
    print("Operations package, executable versions, independent runtimes and Bootstrap payload: PASS")


if __name__ == "__main__":
    main()
