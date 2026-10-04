"""The cache cleaner must never traverse delivery artifacts or user data."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("dry_run", [False, True], ids=["clean", "dry-run"])
def test_cache_cleaner_preserves_artifacts_data_dependencies_and_tracked_files(tmp_path, dry_run):
    shell = shutil.which("powershell.exe") or shutil.which("pwsh")
    git = shutil.which("git")
    if not shell or not git:
        pytest.skip("PowerShell and Git are required for the maintenance-tool regression")
    subprocess.run([git, "init", "--quiet", str(tmp_path)], check=True, capture_output=True)
    script = tmp_path / "scripts/clean_dev_artifacts.ps1"
    script.parent.mkdir()
    shutil.copyfile(ROOT / "scripts/clean_dev_artifacts.ps1", script)
    kept = [
        "dist/portable-v051/__pycache__/artifact.pyc",
        "dist/legacy-importer-v1/__pycache__/artifact.pyc",
        "dist/delivery-v051/__pycache__/artifact.pyc",
        "build/__pycache__/artifact.pyc",
        "backend/data/__pycache__/artifact.pyc",
        "backend/backups/__pycache__/artifact.pyc",
        ".venv/__pycache__/artifact.pyc",
        "frontend/node_modules/__pycache__/artifact.pyc",
        "backend/alembic/__pycache__/tracked.pyc",
        "backend/app/retained.py",
    ]
    removed = [
        "backend/tests/__pycache__/cache.pyc",
        "backend/.mypy_cache/cache.json",
        "frontend/dist/index.html",
    ]
    for relative in kept + removed:
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"maintenance regression sentinel")
    subprocess.run([git, "-C", str(tmp_path), "add", "backend/alembic/__pycache__/tracked.pyc",
                    "backend/app/retained.py"], check=True, capture_output=True)
    arguments = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    if dry_run:
        arguments.append("-DryRun")
    result = subprocess.run(arguments, cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    for relative in kept:
        assert (tmp_path / relative).read_bytes() == b"maintenance regression sentinel"
    for relative in removed:
        assert (tmp_path / relative).exists() is dry_run
