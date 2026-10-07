"""Explicit growth boundaries; Auth, Control Center and CLI are not in scope."""
import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest


APP = Path(__file__).resolve().parents[1] / "app"
GROWTH_SERVICES = (
    "experiment_config", "experiment_identity", "experiment_lifecycle",
    "germination_execution", "sowing_workflow", "seedling_measurement",
    "measurement_query", "measurement_slots", "workbook_export", "application_support",
)
FORBIDDEN = ("app.api", "app.main", "fastapi", "starlette", "app.core.auth",
             "app.core.web", "app.services.common")


def assert_dependencies(source: str, module: str, forbidden=FORBIDDEN):
    targets = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            targets.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = resolve_name("." * node.level + base, module.rpartition(".")[0])
            targets.append((base, node.lineno))
            targets.extend((f"{base}.{alias.name}", node.lineno) for alias in node.names)
    violations = [(target, line) for target, line in targets
                  if any(target == prefix or target.startswith(prefix + ".") for prefix in forbidden)]
    assert not violations, f"{module}: forbidden dependencies {violations}"


@pytest.mark.parametrize("name", GROWTH_SERVICES)
def test_growth_services_do_not_depend_on_transport(name):
    assert_dependencies((APP / "services" / f"{name}.py").read_text(encoding="utf-8"),
                        f"app.services.{name}")


@pytest.mark.parametrize("path", sorted((APP / "contracts").glob("*.py")), ids=lambda p: p.stem)
def test_contracts_do_not_depend_on_adapters_or_implementations(path):
    assert_dependencies(path.read_text(encoding="utf-8"), f"app.contracts.{path.stem}",
                        FORBIDDEN + ("app.services", "app.models", "app.db"))


@pytest.mark.parametrize("source", [
    "from app.api.schemas import MeasurementInput",
    "import app.api.schemas as schemas",
    "from app import api",
    "from ..api.schemas import MeasurementInput",
    "from fastapi import HTTPException",
    "import fastapi as transport",
    "from starlette.exceptions import HTTPException",
    "from app.services.common import require_entity",
    "from .common import require_entity",
])
def test_guard_rejects_injected_forbidden_import(source):
    # Run the same guard on injected source without editing any production file.
    with pytest.raises(AssertionError, match="forbidden dependencies"):
        assert_dependencies(source, "app.services.seedling_measurement")


def test_guard_accepts_contracts_and_business_helpers():
    assert_dependencies("from app.contracts.measurement import MeasurementInput\n"
                        "from .application_support import require_entity\n"
                        "from sqlalchemy.orm import Session", "app.services.seedling_measurement")
