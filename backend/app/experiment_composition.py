"""Static composition root: Core knows the interface, GER provides the workflow."""
from app.core.experiment_types import ExperimentTypeRegistry
from app.services.germination_workflow import germination_registration


def build_experiment_registry() -> ExperimentTypeRegistry:
    return ExperimentTypeRegistry((germination_registration(),))
