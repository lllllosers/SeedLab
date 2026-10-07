"""Read-only experimental population: materials x planned samples x configured DAG.

Exports and future analysis must start here, not at samples or measurements: a
material without obtained seedlings still belongs to the experimental population.
Slots are projections, never persisted entities or lifecycle/failure judgments.
"""
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.contracts.errors import ValidationError
from app.contracts.measurement_dataset import (MeasurementDataset, MeasurementDatasetRow,
                                              MeasurementSlot, MeasurementStage)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (ExperimentMaterial, ExperimentProtocol, GerminationDish,
                        MeasurementTimepoint, SeedlingMeasurement, SeedlingSample)
from app.services.local_time import utc_naive
from app.services.ordering import dish_display_number, sample_display_number
from app.services.measurement_schedule import scheduled_date


@dataclass(frozen=True)
class PlannedSeedlingSlot:
    material: ExperimentMaterial
    sample_scope: str
    planned_number: int
    replicate_no: int | None
    replicate_count: int
    dish: GerminationDish | None
    sample: SeedlingSample | None

    @property
    def key(self) -> tuple[str, int | None, int]:
        return self.material.id, self.replicate_no, self.planned_number

    @property
    def dish_number(self) -> str | None:
        replicate = self.dish.replicate_no if self.dish else self.replicate_no
        return dish_display_number(self.material.experiment_number, replicate, self.replicate_count) if replicate else None

    @property
    def seedling_number(self) -> str | None:
        # Empty pooled slots are not assigned to a fictitious replicate. Their
        # material and planned_number identify the projection in this workbook.
        replicate = self.dish.replicate_no if self.dish else self.replicate_no
        sequence = self.sample.sample_number if self.sample else self.planned_number
        return sample_display_number(self.material.experiment_number, replicate, self.replicate_count, sequence) if replicate else None


@dataclass(frozen=True)
class CanonicalMeasurementSlot:
    seedling: PlannedSeedlingSlot
    timepoint: MeasurementTimepoint
    measurement: SeedlingMeasurement | None

    @property
    def data_status(self) -> str:
        if self.measurement is not None:
            return "已测定"
        return "无测定记录" if self.seedling.sample is not None else "无实际幼苗"


@dataclass(frozen=True)
class CanonicalSlots:
    seedling_slots: tuple[PlannedSeedlingSlot, ...]
    measurement_slots: tuple[CanonicalMeasurementSlot, ...]
    timepoints: tuple[MeasurementTimepoint, ...]


@dataclass(frozen=True)
class MeasurementDatasetReader:
    """Session-bound projection adapter. Analysis uses its structural read port."""
    _db: Session

    def read(self, experiment_ids: Sequence[str]) -> MeasurementDataset:
        return build_measurement_dataset(self._db, list(experiment_ids))


def build_measurement_dataset(db: Session, experiment_ids: list[str]) -> MeasurementDataset:
    """Detach immutable values from the existing canonical slot algorithm.

    Neither ORM instances nor a Session escape into dataset rows. no_autoflush
    covers scalar reads as well as queries, including callers' pending changes.
    Ordering, planned population and validation belong to build_measurement_slots.
    """
    with db.no_autoflush:
        canonical = build_measurement_slots(db, experiment_ids)
        slots = tuple(MeasurementSlot(
            experiment_id=slot.material.experiment_id, material_id=slot.material.id,
            material_number=slot.material.experiment_number, sample_scope=slot.sample_scope,
            planned_number=slot.planned_number, replicate_no=slot.replicate_no,
            replicate_count=slot.replicate_count, dish_id=slot.dish.id if slot.dish else None,
            actual_replicate_no=slot.dish.replicate_no if slot.dish else None,
            sample_id=slot.sample.id if slot.sample else None,
            sample_number=slot.sample.sample_number if slot.sample else None,
            dish_number=slot.dish_number, seedling_number=slot.seedling_number,
            position_label=slot.sample.position_label if slot.sample else None,
            germinated_at=slot.sample.germinated_at if slot.sample else None,
            source_observation_id=slot.sample.source_observation_id if slot.sample else None,
        ) for slot in canonical.seedling_slots)
        by_key = {slot.key: slot for slot in slots}
        stages = tuple(MeasurementStage(point.experiment_id, point.id, point.day_after_germination)
                       for point in canonical.timepoints)
        by_point = {stage.timepoint_id: stage for stage in stages}
        rows = []
        for source in canonical.measurement_slots:
            slot = by_key[source.seedling.key]
            stage = by_point[source.timepoint.id]
            measurement = source.measurement
            rows.append(MeasurementDatasetRow(
                slot=slot, stage=stage,
                scheduled_date=scheduled_date(slot.germinated_at, stage.day_after_germination),
                measurement_id=measurement.id if measurement else None,
                root_length_mm=measurement.root_length_mm if measurement else None,
                shoot_length_mm=measurement.shoot_length_mm if measurement else None,
                root_unavailable=measurement.root_unavailable if measurement else None,
                shoot_unavailable=measurement.shoot_unavailable if measurement else None,
                measured_at=measurement.measured_at if measurement else None,
                notes=measurement.notes if measurement else None,
            ))
        return MeasurementDataset(slots, tuple(rows), stages)


def build_measurement_slots(db: Session, experiment_ids: list[str]) -> CanonicalSlots:
    """LEFT JOIN actual facts onto the full, effective sampling design.

    per_dish: sample_count slots for every designed replicate, including pending
    and cancelled dishes. per_material: a shared sample_count across replicates,
    matched in first-germinated order with replicate/sample identities preserved.
    No missing dates, seedlings, measurements, or lifecycle states are invented.
    Incomplete or inconsistent designs fail explicitly instead of dropping facts.
    """
    with db.no_autoflush:
        return _build(db, experiment_ids)


def _build(db: Session, experiment_ids: list[str]) -> CanonicalSlots:
    materials = list(db.scalars(select(ExperimentMaterial)
                               .where(ExperimentMaterial.experiment_id.in_(experiment_ids))
                               .order_by(ExperimentMaterial.experiment_id, ExperimentMaterial.display_order, ExperimentMaterial.id)))
    protocols = {p.experiment_id: p for p in db.scalars(select(ExperimentProtocol)
                 .where(ExperimentProtocol.experiment_id.in_(experiment_ids)))}
    points = list(db.scalars(select(MeasurementTimepoint)
                  .where(MeasurementTimepoint.experiment_id.in_(experiment_ids))
                  .order_by(MeasurementTimepoint.day_after_germination)))
    points_by_experiment = defaultdict(list)
    point_by_id = {p.id: p for p in points}
    for point in points:
        points_by_experiment[point.experiment_id].append(point)
    dishes = list(db.scalars(select(GerminationDish)
                  .where(GerminationDish.material_id.in_([m.id for m in materials]))))
    dishes_by_material = defaultdict(dict)
    dish_by_id = {dish.id: dish for dish in dishes}
    for dish in dishes:
        dishes_by_material[dish.material_id][dish.replicate_no] = dish
    samples = list(db.scalars(select(SeedlingSample).where(SeedlingSample.dish_id.in_(dish_by_id))))
    samples_by_dish = defaultdict(dict)
    samples_by_material = defaultdict(list)
    for sample in samples:
        dish = dish_by_id[sample.dish_id]
        samples_by_dish[dish.id][sample.sample_number] = sample
        samples_by_material[dish.material_id].append(sample)
    measurements = list(db.scalars(select(SeedlingMeasurement)
                        .where(SeedlingMeasurement.sample_id.in_([s.id for s in samples]))))
    measurements_by_key = {(m.sample_id, m.timepoint_id): m for m in measurements}
    sample_slots = []
    for material in materials:
        protocol = protocols.get(material.experiment_id)
        if protocol is None or protocol.sampling_rule != "first_germinated" or protocol.sample_scope not in {"per_dish", "per_material"}:
            raise ValidationError("部分实验尚未填写支持的取样方式和取样范围，请完善实验方案后再导出科研结果")
        target = material.sample_count_override or protocol.sample_count
        replicates = material.replicate_count_override or protocol.replicate_count
        if not target or not replicates:
            raise ValidationError("部分实验尚未填写取样数和重复数，请完善实验方案后再导出科研结果")
        by_replicate = dishes_by_material[material.id]
        material_samples = samples_by_material[material.id]
        if any(number > replicates for number in by_replicate):
            raise ValidationError("培养皿重复数与实验方案不一致，请核对方案后再导出，避免遗漏实际幼苗")
        if protocol.sample_scope == "per_dish":
            for replicate in range(1, replicates + 1):
                dish = by_replicate.get(replicate)
                actual = samples_by_dish[dish.id] if dish else {}
                if any(number > target for number in actual):
                    raise ValidationError("实际幼苗序号超过每皿取样数，请核对实验方案后再导出，避免遗漏实际幼苗")
                for number in range(1, target + 1):
                    sample_slots.append(PlannedSeedlingSlot(material, protocol.sample_scope, number, replicate,
                                                             replicates, dish, actual.get(number)))
        else:
            if len(material_samples) > target:
                raise ValidationError("实际幼苗数超过每材料取样数，请核对实验方案后再导出，避免遗漏实际幼苗")
            if replicates == 1:
                dish = by_replicate.get(1)
                actual = samples_by_dish[dish.id] if dish else {}
                if any(number > target for number in actual):
                    raise ValidationError("实际幼苗序号超过取样数，请核对实验方案后再导出")
                for number in range(1, target + 1):
                    sample_slots.append(PlannedSeedlingSlot(material, protocol.sample_scope, number, 1, 1,
                                                             dish, actual.get(number)))
            else:
                ordered = sorted(material_samples, key=lambda sample: (
                    utc_naive(sample.germinated_at) if sample.germinated_at else datetime.max,
                    dish_by_id[sample.dish_id].replicate_no, sample.sample_number, sample.id))
                for number in range(1, target + 1):
                    sample = ordered[number-1] if number <= len(ordered) else None
                    dish = dish_by_id[sample.dish_id] if sample else None
                    sample_slots.append(PlannedSeedlingSlot(material, protocol.sample_scope, number, None,
                                                             replicates, dish, sample))
    sample_experiments = {slot.sample.id: slot.material.experiment_id for slot in sample_slots if slot.sample}
    for measurement in measurements:
        point = point_by_id.get(measurement.timepoint_id)
        if point is None or point.experiment_id != sample_experiments[measurement.sample_id]:
            raise ValidationError("实际测定时间点与幼苗所属实验不一致，请核对记录后再导出")
    measurement_slots = tuple(CanonicalMeasurementSlot(slot, point,
        measurements_by_key.get((slot.sample.id, point.id)) if slot.sample else None)
        for slot in sample_slots for point in points_by_experiment[slot.material.experiment_id])
    return CanonicalSlots(tuple(sample_slots), measurement_slots, tuple(points))
