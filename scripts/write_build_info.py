"""One build identity per App, shared by the portable and upgrade manifest."""
import argparse
import json
from pathlib import Path
import subprocess

from app.services.migrations import migration_heads
from app.version import VERSION

ROOT = Path(__file__).resolve().parents[1]


def build_information():
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True))
    heads = migration_heads(ROOT / "backend/alembic")
    if len(heads) != 1:
        raise ValueError("A unique migration head is required")
    return {"application_version": VERSION, "alembic_revision": heads[0], "build_identity": commit + ("-dirty" if dirty else "")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--program", type=Path, required=True)
    args = parser.parse_args()
    target = args.program.resolve()
    if not target.is_relative_to(ROOT / "dist") or target.is_relative_to(ROOT / "dist/portable-v051"):
        raise ValueError("Build identity may only be written to a new distribution")
    (target / "app/build-info.json").write_text(json.dumps(build_information(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
