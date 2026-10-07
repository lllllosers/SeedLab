"""Auth/catalog schemas and compatibility exports of growth contracts."""
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, Field
from app.contracts.base import ORMModel
from app.contracts.experiments import (ExperimentIn, ExperimentPatch, ExperimentOut, ProtocolInput, TerminateExperiment, MaterialInput, MaterialPatch, ConfiguredExperimentInput, DagInput, MaterialOrderInput)
from app.contracts.germination import (SowDishesInput, CorrectSowingInput, CancelDishInput, ObservationEntry, BatchObservationInput, ObservationInput, ObservationPatch)
from app.contracts.measurement import (MeasurementInput, MeasurementPatch, PositionLabelPatch)


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
