"""Explicit growth boundaries; Auth, Control Center and CLI are not in scope."""
import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest


APP = Path(__file__).resolve().parents[1] / "app"
GROWTH_SERVICES = (
    "germination_config", "germination_workflow", "experiment_identity", "experiment_lifecycle",
    "germination_execution", "sowing_workflow", "seedling_measurement",
    "measurement_query", "measurement_slots", "measurement_schedule", "workbook_export", "application_support",
)
FORBIDDEN = ("app.api", "app.main", "fastapi", "starlette", "app.core.auth",
             "app.core.web", "app.services.common", "app.analysis")
CORE_MODULES = ("core/experiment_types.py", "services/experiment_identity.py",
                "services/experiment_lifecycle.py")
CORE_FORBIDDEN = FORBIDDEN + (
    "app.experiment_composition", "app.services.germination_config", "app.services.germination_workflow",
    "app.services.germination_execution", "app.services.sowing_workflow",
    "app.services.seedling_measurement", "app.services.measurement_query",
    "app.services.measurement_slots", "app.services.workbook_export",
    "app.contracts.germination", "app.contracts.measurement",
)
LIFECYCLE_FIELDS = {"status", "started_at", "ended_at", "termination_reason"}
ANALYSIS_FORBIDDEN = tuple(prefix for prefix in FORBIDDEN if prefix != 'app.analysis') + (
    "app.services", "app.models", "app.db", "sqlalchemy", "app.experiment_composition")
MUTATION_CALLS = {"add", "add_all", "delete", "flush", "commit", "rollback", "merge",
                  "bulk_save_objects", "bulk_insert_mappings", "bulk_update_mappings",
                  "insert", "update", "text", "exec_driver_sql"}


def import_base(node, module):
    base = node.module or ""
    return resolve_name("." * node.level + base, module.rpartition(".")[0]) if node.level else base


def assert_dependencies(source: str, module: str, forbidden=FORBIDDEN):
    targets = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            targets.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = import_base(node, module)
            targets.append((base, node.lineno))
            targets.extend((f"{base}.{alias.name}", node.lineno) for alias in node.names)
    violations = [(target, line) for target, line in targets
                  if any(target == prefix or target.startswith(prefix + ".") for prefix in forbidden)]
    assert not violations, f"{module}: forbidden dependencies {violations}"


def assert_core_dependencies(source: str, module: str):
    assert_dependencies(source, module, CORE_FORBIDDEN)
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            assert all(alias.name not in {"app.models", "app.models.entities"} for alias in node.names), \
                "Core must explicitly import generic ORM names"
        elif isinstance(node, ast.ImportFrom):
            base = import_base(node, module)
            if base in {"app.models", "app.models.entities"}:
                assert all(alias.name in {"Experiment", "ExperimentMaterial", "now_utc"} for alias in node.names), \
                    "Core imports GER-specific ORM"
            if base == "app":
                assert all(alias.name != "models" for alias in node.names), "Core must explicitly import generic ORM names"
            if base == "app.contracts.experiments":
                assert all(alias.name in {"ExperimentIn", "ExperimentOut", "ExperimentPatch", "TerminateExperiment"}
                           for alias in node.names), "Core imports GER design DTO"


def assert_lifecycle_writes(source: str, module: str):
    if module == "app.services.experiment_lifecycle":
        return
    tree = ast.parse(source)
    for function in (node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
        # Identify actual Experiment variables instead of rejecting unrelated .status fields.
        experiments = {arg.arg for arg in function.args.args
                       if isinstance(arg.annotation, ast.Name) and arg.annotation.id == "Experiment"
                       or isinstance(arg.annotation, ast.Constant) and arg.annotation.value == "Experiment"}
        nodes = list(ast.walk(function))
        for node in nodes:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value
                is_experiment = (
                    isinstance(call.func, ast.Name) and call.func.id == "Experiment"
                    or isinstance(call.func, ast.Name) and call.func.id == "require_entity" and len(call.args) > 1
                       and isinstance(call.args[1], ast.Name) and call.args[1].id == "Experiment"
                    or isinstance(call.func, ast.Attribute) and call.func.attr == "get" and call.args
                       and isinstance(call.args[0], ast.Name) and call.args[0].id == "Experiment")
                if is_experiment:
                    experiments.update(target.id for target in node.targets if isinstance(target, ast.Name))
        changed = True
        while changed:
            previous = set(experiments)
            for node in nodes:
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id in experiments:
                    experiments.update(target.id for target in node.targets if isinstance(target, ast.Name))
            changed = previous != experiments
        for node in nodes:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] \
                if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
            for target in targets:
                assert not (isinstance(target, ast.Attribute) and target.attr in LIFECYCLE_FIELDS
                            and isinstance(target.value, ast.Name) and target.value.id in experiments), \
                    f"{module}:{node.lineno}: Experiment lifecycle write outside authority"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "setattr" \
                    and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and node.args[0].id in experiments:
                assert not (isinstance(node.args[1], ast.Constant) and node.args[1].value in LIFECYCLE_FIELDS), \
                    f"{module}:{node.lineno}: Experiment lifecycle write outside authority"


def assert_readonly_projection(source: str):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id \
                if isinstance(node.func, ast.Name) else ''
            assert name not in MUTATION_CALLS, f"projection mutation call: {name}"
            assert name not in {"ExperimentMaterial", "GerminationDish", "SeedlingSample", "SeedlingMeasurement",
                                "MeasurementTimepoint", "ExperimentProtocol"}, "projection constructs fake ORM"
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] \
            if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
        assert not any(isinstance(target, ast.Attribute) for target in targets), "projection writes entity attribute"


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


@pytest.mark.parametrize("relative", CORE_MODULES)
def test_core_does_not_depend_on_ger_implementation(relative):
    path = APP / relative
    assert_core_dependencies(path.read_text(encoding="utf-8"), "app." + relative[:-3].replace("/", "."))


@pytest.mark.parametrize("source", [
    "from app.services.germination_workflow import GerminationWorkflow",
    "from .germination_config import validate_all",
    "from app.services import sowing_workflow",
    "from app.experiment_composition import build_experiment_registry",
    "from app.models import GerminationDish",
    "from ..models.entities import SeedlingSample",
    "import app.models as models",
    "from app.models import *",
    "from app.contracts.experiments import ProtocolInput",
])
def test_core_guard_rejects_injected_ger_dependency(source):
    with pytest.raises(AssertionError):
        assert_core_dependencies(source, "app.services.experiment_lifecycle")


def test_ger_to_core_interface_dependency_is_allowed():
    assert_dependencies("from app.core.experiment_types import ExperimentTypeRegistration\n"
                        "from app.services.experiment_lifecycle import activate_from_fact",
                        "app.services.germination_workflow")


def test_only_core_authority_writes_experiment_lifecycle():
    for path in sorted(APP.rglob("*.py")):
        module = "app." + path.relative_to(APP).with_suffix("").as_posix().replace("/", ".")
        assert_lifecycle_writes(path.read_text(encoding="utf-8"), module)


@pytest.mark.parametrize("mutation", ["experiment.status = 'active'", "experiment.started_at = None",
                                      "setattr(experiment, 'ended_at', None)",
                                      "alias = experiment\n    alias.termination_reason = 'changed'"])
def test_lifecycle_guard_rejects_injected_write(mutation):
    with pytest.raises(AssertionError, match="lifecycle write outside authority"):
        assert_lifecycle_writes("def start(db):\n    experiment = require_entity(db, Experiment, 'id')\n    " + mutation,
                                "app.services.sowing_workflow")


def test_lifecycle_guard_allows_other_entities_and_default_creation():
    assert_lifecycle_writes("def update(job):\n    job.status = 'completed'\n"
                            "def create():\n    experiment = Experiment(name='草稿实验')",
                            "app.services.material_import")


@pytest.mark.parametrize('path', sorted((APP / 'analysis').glob('*.py')), ids=lambda p: p.stem)
def test_analysis_only_depends_on_neutral_dataset_contracts(path):
    assert_dependencies(path.read_text(encoding='utf-8'), f'app.analysis.{path.stem}', ANALYSIS_FORBIDDEN)


@pytest.mark.parametrize('module', ['app.services.experiment_lifecycle', 'app.services.germination_workflow',
                                   'app.services.seedling_measurement'])
@pytest.mark.parametrize('source', ['import app.analysis.datasets', 'from app import analysis',
                                   'from ..analysis.datasets import read_dataset'])
def test_guard_rejects_core_ger_measurement_to_analysis(module, source):
    with pytest.raises(AssertionError, match='forbidden dependencies'):
        assert_dependencies(source, module)


@pytest.mark.parametrize('source', ['from app.api import measurement', 'from fastapi import Depends',
                                   'import starlette', 'from app.services.seedling_measurement import create',
                                   'from app.services.measurement_slots import MeasurementDatasetReader',
                                   'from app.models import SeedlingSample', 'from sqlalchemy.orm import Session'])
def test_guard_rejects_analysis_transport_orm_and_implementation_imports(source):
    with pytest.raises(AssertionError, match='forbidden dependencies'):
        assert_dependencies(source, 'app.analysis.datasets', ANALYSIS_FORBIDDEN)


def test_canonical_projection_has_no_fact_mutation_or_fake_orm():
    assert_readonly_projection((APP / 'services/measurement_slots.py').read_text(encoding='utf-8'))


@pytest.mark.parametrize('source', ['db.add(sample)', 'db.commit()', 'delete(SeedlingSample)',
                                   'db.execute(update(SeedlingMeasurement))', 'db.exec_driver_sql(sql)',
                                   'sample.root_length_mm = 0', 'fake = SeedlingSample(sample_number=1)'])
def test_readonly_guard_rejects_injected_fact_mutations(source):
    with pytest.raises(AssertionError, match='projection'):
        assert_readonly_projection(source)
