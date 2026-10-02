"""Read-only experimental population: materials x planned samples x configured DAG.

Exports and future analysis must start here, not at samples or measurements: a
material without obtained seedlings still belongs to the experimental population.
Slots are projections, never persisted entities or lifecycle/failure judgments.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (ExperimentMaterial, ExperimentProtocol, GerminationDish,
                        MeasurementTimepoint, SeedlingMeasurement, SeedlingSample)
from app.services.local_time import utc_naive
from app.services.ordering import dish_display_number, sample_display_number


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
            raise HTTPException(422, "部分实验尚未填写支持的取样方式和取样范围，请完善实验方案后再导出科研结果")
        target = material.sample_count_override or protocol.sample_count
        replicates = material.replicate_count_override or protocol.replicate_count
        if not target or not replicates:
            raise HTTPException(422, "部分实验尚未填写取样数和重复数，请完善实验方案后再导出科研结果")
        by_replicate = dishes_by_material[material.id]
        material_samples = samples_by_material[material.id]
        if any(number > replicates for number in by_replicate):
            raise HTTPException(422, "培养皿重复数与实验方案不一致，请核对方案后再导出，避免遗漏实际幼苗")
        if protocol.sample_scope == "per_dish":
            for replicate in range(1, replicates + 1):
                dish = by_replicate.get(replicate)
                actual = samples_by_dish[dish.id] if dish else {}
                if any(number > target for number in actual):
                    raise HTTPException(422, "实际幼苗序号超过每皿取样数，请核对实验方案后再导出，避免遗漏实际幼苗")
                for number in range(1, target + 1):
                    sample_slots.append(PlannedSeedlingSlot(material, protocol.sample_scope, number, replicate,
                                                             replicates, dish, actual.get(number)))
        else:
            if len(material_samples) > target:
                raise HTTPException(422, "实际幼苗数超过每材料取样数，请核对实验方案后再导出，避免遗漏实际幼苗")
            if replicates == 1:
                dish = by_replicate.get(1)
                actual = samples_by_dish[dish.id] if dish else {}
                if any(number > target for number in actual):
                    raise HTTPException(422, "实际幼苗序号超过取样数，请核对实验方案后再导出")
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
            raise HTTPException(422, "实际测定时间点与幼苗所属实验不一致，请核对记录后再导出")
    measurement_slots = tuple(CanonicalMeasurementSlot(slot, point,
        measurements_by_key.get((slot.sample.id, point.id)) if slot.sample else None)
        for slot in sample_slots for point in points_by_experiment[slot.material.experiment_id])
    return CanonicalSlots(tuple(sample_slots), measurement_slots, tuple(points))
