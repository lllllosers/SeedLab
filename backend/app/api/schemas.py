from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, computed_field
from app.core.experiment_types import ExperimentType, EXPERIMENT_TYPES


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORMModel):
    id: str
    username: str
    display_name: str
    is_admin: bool
    is_active: bool
    must_change_password: bool


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    is_admin: bool = False


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    is_admin: bool | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str


class BootstrapInput(BaseModel):
    bootstrap_token: str
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str


class Login(BaseModel):
    username: str
    password: str


class TaxonIn(BaseModel):
    scientific_name: str = Field(min_length=2, max_length=255)
    common_name: str | None = Field(default=None, max_length=255)
    family: str | None = Field(default=None, max_length=255)
    genus: str | None = Field(default=None, max_length=255)
    life_form: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class TaxonPatch(BaseModel):
    scientific_name: str | None = Field(default=None, min_length=2, max_length=255)
    common_name: str | None = Field(default=None, max_length=255)
    family: str | None = Field(default=None, max_length=255)
    genus: str | None = Field(default=None, max_length=255)
    life_form: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    is_active: bool | None = None


class TaxonOut(ORMModel):
    id: str
    code: str
    scientific_name: str
    common_name: str | None
    family: str | None
    genus: str | None
    life_form: str | None
    notes: str | None
    is_active: bool
    created_at: datetime


class SeedLotIn(BaseModel):
    taxon_id: str
    source: str | None = Field(default=None, max_length=255)
    source_code: str | None = Field(default=None, max_length=120)
    collected_at: AwareDatetime | None = None
    quantity: int | None = Field(default=None, ge=0)
    notes: str | None = None


class SeedLotPatch(BaseModel):
    source: str | None = Field(default=None, max_length=255)
    source_code: str | None = Field(default=None, max_length=120)
    collected_at: AwareDatetime | None = None
    quantity: int | None = Field(default=None, ge=0)
    notes: str | None = None
    is_active: bool | None = None


class SeedLotOut(ORMModel):
    id: str
    code: str
    taxon_id: str
    taxon: TaxonOut
    source: str | None
    source_code: str | None
    collected_at: datetime | None
    quantity: int | None
    notes: str | None
    is_active: bool
    created_at: datetime


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
    observation_period_days: int = Field(gt=0)
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


class SowDishesInput(BaseModel):
    dish_ids: list[str] = Field(min_length=1)
    sown_at: AwareDatetime


class CorrectSowingInput(BaseModel):
    sown_at: AwareDatetime


class CancelDishInput(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class ObservationEntry(BaseModel):
    dish_id: str
    new_germinated_count: int | None = Field(default=None, ge=0)
    notes: str | None = None


class BatchObservationInput(BaseModel):
    observed_at: AwareDatetime
    entries: list[ObservationEntry] = Field(min_length=1)


class ObservationInput(ObservationEntry):
    observed_at: AwareDatetime
    new_germinated_count: int = Field(ge=0)


class ObservationPatch(BaseModel):
    new_germinated_count: int | None = Field(default=None, ge=0)
    notes: str | None = None


class MeasurementInput(BaseModel):
    sample_id: str
    timepoint_id: str
    root_length_mm: Decimal | None = None
    shoot_length_mm: Decimal | None = None
    root_unavailable: bool = False
    shoot_unavailable: bool = False
    measured_at: AwareDatetime
    notes: str | None = None


class MeasurementPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    root_length_mm: Decimal | None = None
    shoot_length_mm: Decimal | None = None
    root_unavailable: bool | None = None
    shoot_unavailable: bool | None = None
    measured_at: AwareDatetime | None = None
    notes: str | None = None


class PositionLabelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    position_label: str | None = Field(default=None, max_length=80)
