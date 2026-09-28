from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORMModel):
    id: str
    username: str
    display_name: str
    is_admin: bool
    is_active: bool


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=128)
    is_admin: bool = False


class Login(BaseModel):
    username: str
    password: str


class TaxonIn(BaseModel):
    scientific_name: str = Field(min_length=2, max_length=255)
    common_name: str | None = Field(default=None, max_length=255)
    family: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class TaxonPatch(BaseModel):
    scientific_name: str | None = Field(default=None, min_length=2, max_length=255)
    common_name: str | None = Field(default=None, max_length=255)
    family: str | None = Field(default=None, max_length=255)
    notes: str | None = None
    is_active: bool | None = None


class TaxonOut(ORMModel):
    id: str
    code: str
    scientific_name: str
    common_name: str | None
    family: str | None
    notes: str | None
    is_active: bool
    created_at: datetime


class SeedLotIn(BaseModel):
    taxon_id: str
    source: str | None = Field(default=None, max_length=255)
    quantity: int | None = Field(default=None, ge=0)
    notes: str | None = None


class SeedLotPatch(BaseModel):
    source: str | None = Field(default=None, max_length=255)
    quantity: int | None = Field(default=None, ge=0)
    notes: str | None = None
    is_active: bool | None = None


class SeedLotOut(ORMModel):
    id: str
    code: str
    taxon_id: str
    source: str | None
    quantity: int | None
    notes: str | None
    is_active: bool
    created_at: datetime


class ExperimentIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None


class ExperimentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    status: Literal["draft", "active", "completed", "cancelled"] | None = None


class ExperimentOut(ORMModel):
    id: str
    code: str
    name: str
    description: str | None
    status: str
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class AuditOut(ORMModel):
    id: str
    user_id: str | None
    action: str
    entity_type: str
    entity_id: str
    before: dict | None
    after: dict | None
    created_at: datetime
