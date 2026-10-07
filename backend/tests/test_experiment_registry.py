"""The static composition exposes only the current GER workflow."""
from dataclasses import FrozenInstanceError

import pytest

from app.contracts.errors import ValidationError
from app.core.experiment_types import EXPERIMENT_TYPES, ExperimentTypeRegistry
from app.experiment_composition import build_experiment_registry
from app.services.germination_workflow import GerminationWorkflow, germination_registration


def test_ger_is_registered_exactly_once_with_current_metadata():
    registry = build_experiment_registry()
    entries = registry.entries()
    assert len(entries) == 1
    assert entries[0].code == "GER"
    assert entries[0].label == "种子萌发试验" == EXPERIMENT_TYPES["GER"]
    assert isinstance(entries[0].workflow, GerminationWorkflow)
    assert registry.require("GER") is entries[0]


@pytest.mark.parametrize("code", ["ALT", "ger", ""])
def test_unknown_type_is_rejected(code):
    with pytest.raises(ValidationError, match="不支持该实验类型，请重新选择实验类型"):
        build_experiment_registry().require(code)


def test_duplicate_registration_is_rejected_during_composition():
    entry = germination_registration()
    with pytest.raises(ValueError, match="Duplicate experiment type: GER"):
        ExperimentTypeRegistry((entry, entry))


def test_metadata_is_immutable_and_composition_is_deterministic():
    first, second = build_experiment_registry(), build_experiment_registry()
    assert [(entry.code, entry.label) for entry in first.entries()] == [
        (entry.code, entry.label) for entry in second.entries()] == [("GER", "种子萌发试验")]
    with pytest.raises(FrozenInstanceError):
        first.require("GER").label = "changed"
    with pytest.raises(TypeError):
        EXPERIMENT_TYPES["GER"] = "changed"
    assert first.require("GER").workflow is not second.require("GER").workflow


def test_types_api_keeps_exact_payload_and_uses_application_registry(auth_client):
    client, _ = auth_client
    response = client.get("/api/experiments/types")
    assert response.status_code == 200
    assert response.json() == [{"value": "GER", "label": "种子萌发试验"}]
    assert len(client.app.state.experiment_types.entries()) == 1
