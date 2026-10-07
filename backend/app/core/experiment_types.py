"""Core-owned type metadata, workflow boundary and immutable registry."""
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol

from app.contracts.errors import ValidationError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from app.models import Experiment

ExperimentType = Literal["GER"]
EXPERIMENT_TYPES = MappingProxyType({"GER": "种子萌发试验"})


class ExperimentTypeWorkflow(Protocol):
    def require_editable(self, experiment: "Experiment") -> None: ...
    def require_patch_transition(self, experiment: "Experiment", target: str) -> None: ...
    def require_ready(self, db: "Session", experiment: "Experiment") -> None: ...
    def completion_check(self, db: "Session", experiment: "Experiment") -> dict: ...
    def require_complete(self, db: "Session", experiment: "Experiment") -> None: ...
    def has_facts(self, db: "Session", experiment: "Experiment") -> bool: ...
    def cleanup_unused(self, db: "Session", experiment: "Experiment") -> None: ...


@dataclass(frozen=True)
class ExperimentTypeRegistration:
    code: ExperimentType
    label: str
    workflow: ExperimentTypeWorkflow


class ExperimentTypeRegistry:
    """Construct once at composition; there is no runtime registration API."""
    def __init__(self, registrations: tuple[ExperimentTypeRegistration, ...]):
        entries = {}
        for entry in registrations:
            if entry.code in entries:
                raise ValueError(f"Duplicate experiment type: {entry.code}")
            if EXPERIMENT_TYPES.get(entry.code) != entry.label:
                raise ValueError(f"Unsupported experiment type metadata: {entry.code}")
            entries[entry.code] = entry
        self._entries = MappingProxyType(dict(sorted(entries.items())))

    def entries(self) -> tuple[ExperimentTypeRegistration, ...]:
        return tuple(self._entries.values())

    def require(self, code: str) -> ExperimentTypeRegistration:
        try:
            return self._entries[code]
        except KeyError:
            raise ValidationError("不支持该实验类型，请重新选择实验类型") from None
