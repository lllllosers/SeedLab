"""Measurement input contracts; zero, unavailable and missing stay distinct."""
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


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
