"""Resolve the registry assembled for this application instance."""
from fastapi import Request

from app.core.experiment_types import ExperimentTypeRegistry


def get_experiment_registry(request: Request) -> ExperimentTypeRegistry:
    return request.app.state.experiment_types
