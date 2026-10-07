"""Immutable projections of planned slots and actual root/shoot facts, not ORM.

No statistical fields, persistence, transport, or mutation methods belong here.
Missing samples/measurements remain absent; numeric zero and independent
unavailable flags retain the facts' meaning.
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal


@dataclass(frozen=True)
class MeasurementSlot:
    experiment_id: str
    material_id: str
    material_number: int | None
    sample_scope: str
    planned_number: int
    replicate_no: int | None
    replicate_count: int
    dish_id: str | None
    actual_replicate_no: int | None
    sample_id: str | None
    sample_number: int | None
    dish_number: str | None
    seedling_number: str | None
    position_label: str | None
    germinated_at: datetime | None
    source_observation_id: str | None

    @property
    def key(self) -> tuple[str, int | None, int]:
        return self.material_id, self.replicate_no, self.planned_number


@dataclass(frozen=True)
class MeasurementStage:
    experiment_id: str
    timepoint_id: str
    day_after_germination: int


@dataclass(frozen=True)
class MeasurementDatasetRow:
    slot: MeasurementSlot
    stage: MeasurementStage
    scheduled_date: date | None
    measurement_id: str | None
    root_length_mm: Decimal | None
    shoot_length_mm: Decimal | None
    root_unavailable: bool | None
    shoot_unavailable: bool | None
    measured_at: datetime | None
    notes: str | None

    @property
    def measurement_exists(self) -> bool:
        return self.measurement_id is not None

    @property
    def data_status(self) -> str:
        if self.measurement_exists:
            return '已测定'
        return '无测定记录' if self.slot.sample_id is not None else '无实际幼苗'


@dataclass(frozen=True)
class MeasurementDataset:
    seedling_slots: tuple[MeasurementSlot, ...]
    rows: tuple[MeasurementDatasetRow, ...]
    stages: tuple[MeasurementStage, ...]
