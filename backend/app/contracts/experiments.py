"""Experiment design contracts; existing GER assumptions are preserved."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.contracts.base import ORMModel
from app.core.experiment_types import ExperimentType, EXPERIMENT_TYPES


class ExperimentIn(BaseModel):
    experiment_type: ExperimentType
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    planned_start_date: date | None = None


class ExperimentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    planned_start_date: date | None = None
    status: Literal["draft", "ready", "active", "completed", "cancelled"] | None = None


class ExperimentOut(ORMModel):
    id: str
    code: str
    experiment_type: ExperimentType

    @computed_field
    @property
    def experiment_type_label(self) -> str:
        return EXPERIMENT_TYPES[self.experiment_type]

    name: str
    description: str | None
    status: str
    planned_start_date: date | None
    owner_id: str | None
    started_at: datetime | None
    numbering_locked_at: datetime | None
    ended_at: datetime | None
    termination_reason: str | None
    created_at: datetime


class ProtocolInput(BaseModel):
    seeds_per_dish: int = Field(gt=0)
    replicate_count: int = Field(gt=0)
    observation_period_days: int | None = Field(default=None, gt=0)
    sampling_rule: str = Field(default="first_germinated", min_length=1, max_length=40)
    sample_count: int = Field(gt=0)
    sample_scope: Literal["per_dish", "per_material"] = "per_dish"
    germination_criterion: str = Field(min_length=1)
    summary: str | None = None


class TerminateExperiment(BaseModel):
    reason: str = Field(min_length=1)


class MaterialInput(BaseModel):
    seed_lot_id: str
    label: str | None = Field(default=None, max_length=120)
    seeds_per_dish_override: int | None = Field(default=None, gt=0)
    replicate_count_override: int | None = Field(default=None, gt=0)
    sample_count_override: int | None = Field(default=None, gt=0)


class MaterialPatch(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    seeds_per_dish_override: int | None = Field(default=None, gt=0)
    replicate_count_override: int | None = Field(default=None, gt=0)
    sample_count_override: int | None = Field(default=None, gt=0)


class ConfiguredExperimentInput(ExperimentIn):
    protocol: ProtocolInput
    materials: list[MaterialInput] = Field(min_length=1)
    dag_days: list[int] = Field(min_length=1)


class DagInput(BaseModel):
    days: list[int] = Field(min_length=1)


class MaterialOrderInput(BaseModel):
    material_ids: list[str]
