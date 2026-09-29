"""Derived DAG work queue and immutable sample identity with auditable measurements."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import MeasurementInput, MeasurementPatch
from app.models import (Experiment, ExperimentMaterial, GerminationDish, MeasurementTimepoint,
                        SeedlingMeasurement, SeedlingSample, SeedLot, Taxon)
from app.services.common import commit_or_conflict, flush_or_conflict, record, require_entity
from app.services.local_time import iso_utc, local_date, today, utc_naive
from app.services.ordering import display_number, field_number


def _rows(db: Session, experiment_id: str):
    return db.execute(select(SeedlingSample, GerminationDish, ExperimentMaterial, SeedLot, Taxon)
                      .join(GerminationDish, SeedlingSample.dish_id == GerminationDish.id)
                      .join(ExperimentMaterial, GerminationDish.material_id == ExperimentMaterial.id)
                      .join(SeedLot, ExperimentMaterial.seed_lot_id == SeedLot.id)
                      .join(Taxon, SeedLot.taxon_id == Taxon.id)
                      .where(ExperimentMaterial.experiment_id == experiment_id)
                      .order_by(ExperimentMaterial.display_order, GerminationDish.replicate_no,
                                SeedlingSample.sample_number)).all()


def _measurement_state(item: SeedlingMeasurement) -> dict:
    return {"id": item.id, "sample_id": item.sample_id, "timepoint_id": item.timepoint_id,
            "root_length_mm": float(item.root_length_mm) if item.root_length_mm is not None else None,
            "shoot_length_mm": float(item.shoot_length_mm) if item.shoot_length_mm is not None else None,
            "root_unavailable": item.root_unavailable, "shoot_unavailable": item.shoot_unavailable,
            "measured_at": iso_utc(item.measured_at), "notes": item.notes}


def scheduled_date(germinated_at, dag: int):
    return local_date(germinated_at) + timedelta(days=dag) if germinated_at else None


def task_data(db: Session, experiment_id: str, status: str | None = None,
              dag: int | None = None, q: str | None = None) -> dict:
    experiment = require_entity(db, Experiment, experiment_id)
    if status not in {None, "pending", "due_today", "overdue", "upcoming", "completed", "unschedulable"}:
        raise HTTPException(422, "请选择有效的测定任务状态")
    days = list(db.scalars(select(MeasurementTimepoint).where(MeasurementTimepoint.experiment_id == experiment_id)
                           .order_by(MeasurementTimepoint.day_after_germination)))
    if dag is not None and dag not in {point.day_after_germination for point in days}:
        raise HTTPException(422, "该实验没有所选的发芽后测定时间")
    rows = _rows(db, experiment_id)
    counts = dict(db.execute(select(GerminationDish.material_id, func.max(GerminationDish.replicate_no))
                             .join(ExperimentMaterial, GerminationDish.material_id == ExperimentMaterial.id)
                             .where(ExperimentMaterial.experiment_id == experiment_id)
                             .group_by(GerminationDish.material_id)).all())
    sample_ids = [sample.id for sample, *_ in rows]
    measurements = { (item.sample_id, item.timepoint_id): item for item in db.scalars(
        select(SeedlingMeasurement).where(SeedlingMeasurement.sample_id.in_(sample_ids)))} if sample_ids else {}
    local_today = today()
    summary = {"due_today_count": 0, "overdue_count": 0, "completed_today_count": 0,
               "upcoming_count": 0, "unschedulable_count": 0}
    tasks = []
    needle = (q or "").strip().casefold()
    for sample, dish, material, lot, taxon in rows:
        number = display_number(material.experiment_number) if material.experiment_number else None
        field = field_number(material, counts[material.id], dish.replicate_no) if number else dish.code
        haystack = (number, field, dish.code, taxon.common_name, taxon.scientific_name,
                    taxon.code, lot.code, lot.source_code, str(sample.sample_number),
                    f"幼苗 {sample.sample_number:02d}", sample.position_label)
        for point in days:
            measurement = measurements.get((sample.id, point.id))
            planned = scheduled_date(sample.germinated_at, point.day_after_germination)
            if measurement:
                state = "completed"
                if local_date(measurement.measured_at) == local_today:
                    summary["completed_today_count"] += 1
            elif planned is None:
                state = "unschedulable"
                summary["unschedulable_count"] += 1
            elif planned < local_today:
                state = "overdue"
                summary["overdue_count"] += 1
            elif planned == local_today:
                state = "due_today"
                summary["due_today_count"] += 1
            else:
                state = "upcoming"
                summary["upcoming_count"] += 1
            if status == "pending" and state not in {"overdue", "due_today"}:
                continue
            if status not in {None, "pending"} and state != status:
                continue
            if dag is not None and point.day_after_germination != dag:
                continue
            if needle and not any(needle in str(value).casefold() for value in haystack if value is not None):
                continue
            tasks.append({"experiment_id": experiment.id, "experiment_code": experiment.code,
                          "material_id": material.id, "experiment_number": number,
                          "dish_id": dish.id, "dish_code": dish.code, "field_number": field,
                          "replicate_no": dish.replicate_no, "sample_id": sample.id,
                          "sample_number": sample.sample_number, "position_label": sample.position_label,
                          "taxon_common_name": taxon.common_name, "taxon_scientific_name": taxon.scientific_name,
                          "taxon_code": taxon.code, "seed_lot_code": lot.code, "source_code": lot.source_code,
                          "germinated_at": iso_utc(sample.germinated_at), "timepoint_id": point.id,
                          "day_after_germination": point.day_after_germination,
                          "scheduled_date": planned.isoformat() if planned else None, "status": state,
                          "measurement_id": measurement.id if measurement else None,
                          "root_length_mm": float(measurement.root_length_mm) if measurement and measurement.root_length_mm is not None else None,
                          "shoot_length_mm": float(measurement.shoot_length_mm) if measurement and measurement.shoot_length_mm is not None else None,
                          "root_unavailable": measurement.root_unavailable if measurement else False,
                          "shoot_unavailable": measurement.shoot_unavailable if measurement else False,
                          "measured_at": iso_utc(measurement.measured_at) if measurement else None,
                          "notes": measurement.notes if measurement else None,
                          "delay_days": (local_date(measurement.measured_at) - planned).days if measurement and planned else None})
    priority = {"overdue": 0, "due_today": 1, "upcoming": 2, "unschedulable": 3, "completed": 4}
    tasks.sort(key=lambda item: (priority[item["status"]], item["scheduled_date"] or "",
                                 item["experiment_number"] or "", item["replicate_no"],
                                 item["sample_number"], item["day_after_germination"]))
    return {"experiment_status": experiment.status, "dag_days": [point.day_after_germination for point in days],
            "summary": summary, "tasks": tasks}


def history(db: Session, experiment_id: str, material_id: str) -> dict:
    require_entity(db, Experiment, experiment_id)
    material = require_entity(db, ExperimentMaterial, material_id)
    if material.experiment_id != experiment_id:
        raise HTTPException(404, "该实验没有所选材料")
    derived = task_data(db, experiment_id)
    tasks = [item for item in derived["tasks"] if item["material_id"] == material_id]
    samples = {}
    for task in tasks:
        sample = samples.setdefault(task["sample_id"], {"sample_id": task["sample_id"],
            "sample_number": task["sample_number"], "field_number": task["field_number"],
            "position_label": task["position_label"], "germinated_at": task["germinated_at"], "measurements": {}})
        sample["measurements"][str(task["day_after_germination"])] = task
    return {"dag_days": derived["dag_days"],
            "samples": sorted(samples.values(), key=lambda row: (row["field_number"], row["sample_number"]))}


def _ownership(db: Session, experiment_id: str, sample_id: str, timepoint_id: str):
    sample = require_entity(db, SeedlingSample, sample_id)
    dish = require_entity(db, GerminationDish, sample.dish_id)
    material = require_entity(db, ExperimentMaterial, dish.material_id)
    point = require_entity(db, MeasurementTimepoint, timepoint_id)
    if material.experiment_id != experiment_id or point.experiment_id != experiment_id:
        raise HTTPException(422, "幼苗与测定时间必须属于当前实验")
    if sample.germinated_at is None:
        raise HTTPException(422, "这株幼苗缺少发芽判定时间，暂时无法安排测定；请先核对历史样本")
    return sample, point


def _validate(values: dict, sample: SeedlingSample, point: MeasurementTimepoint) -> dict:
    for part, label in (("root", "根长"), ("shoot", "苗长")):
        key = f"{part}_length_mm"
        unavailable = values[f"{part}_unavailable"]
        raw = values[key]
        if unavailable is None or (raw is None) == (unavailable is False):
            raise HTTPException(422, f"{label}请填写非负数值，或选择无法测量")
        if raw is not None:
            try:
                number = Decimal(str(raw))
                if not number.is_finite() or number < 0 or number.as_tuple().exponent < -2 or number > Decimal("99999999.99"):
                    raise ValueError
            except (InvalidOperation, ValueError):
                raise HTTPException(422, f"{label}请填写不超过两位小数的非负数值") from None
            values[key] = number
    measured = values["measured_at"]
    if measured is None:
        raise HTTPException(422, "请填写实际测定时间")
    planned = scheduled_date(sample.germinated_at, point.day_after_germination)
    if local_date(measured) < planned:
        raise HTTPException(422, f"该幼苗的 DAG {point.day_after_germination} 计划测定日期为{planned.month}月{planned.day}日，当前测定时间早于计划日期")
    values["measured_at"] = utc_naive(measured)
    return values


def create(db: Session, experiment_id: str, data: MeasurementInput, user_id: str) -> dict:
    experiment = require_entity(db, Experiment, experiment_id)
    if experiment.status != "active":
        raise HTTPException(409, "只有进行中的实验可以新增幼苗测定")
    sample, point = _ownership(db, experiment_id, data.sample_id, data.timepoint_id)
    if db.scalar(select(SeedlingMeasurement.id).where(SeedlingMeasurement.sample_id == sample.id,
                                                     SeedlingMeasurement.timepoint_id == point.id)):
        raise HTTPException(409, "这株幼苗在该发芽后测定时间已有记录，请打开历史记录修改")
    values = _validate(data.model_dump(exclude={"sample_id", "timepoint_id"}), sample, point)
    item = SeedlingMeasurement(sample_id=sample.id, timepoint_id=point.id, **values)
    db.add(item)
    flush_or_conflict(db)
    after = _measurement_state(item)
    record(db, user_id, "create", "SeedlingMeasurement", item.id, None, after)
    commit_or_conflict(db)
    return after


def _existing(db: Session, experiment_id: str, measurement_id: str):
    experiment = require_entity(db, Experiment, experiment_id)
    item = require_entity(db, SeedlingMeasurement, measurement_id)
    sample, point = _ownership(db, experiment_id, item.sample_id, item.timepoint_id)
    return experiment, item, sample, point


def update(db: Session, experiment_id: str, measurement_id: str, data: MeasurementPatch, user_id: str) -> dict:
    experiment, item, sample, point = _existing(db, experiment_id, measurement_id)
    if experiment.status not in {"active", "completed"}:
        raise HTTPException(409, "当前实验状态不允许修改幼苗测定")
    before = _measurement_state(item)
    values = {key: getattr(item, key) for key in ("root_length_mm", "shoot_length_mm", "root_unavailable",
              "shoot_unavailable", "measured_at", "notes")}
    values.update(data.model_dump(exclude_unset=True))
    values = _validate(values, sample, point)
    for key, value in values.items():
        setattr(item, key, value)
    after = _measurement_state(item)
    if before != after:
        record(db, user_id, "update", "SeedlingMeasurement", item.id, before, after)
        commit_or_conflict(db)
    return after


def delete(db: Session, experiment_id: str, measurement_id: str, user_id: str) -> None:
    experiment, item, _, _ = _existing(db, experiment_id, measurement_id)
    if experiment.status != "active":
        raise HTTPException(409, "只有进行中的实验可以清除本阶段测定；已完成实验仍可修改原记录")
    before = _measurement_state(item)
    db.delete(item)
    flush_or_conflict(db)
    record(db, user_id, "delete", "SeedlingMeasurement", measurement_id, before, None)
    commit_or_conflict(db)


def update_position(db: Session, experiment_id: str, sample_id: str,
                    position_label: str | None, user_id: str) -> dict:
    experiment = require_entity(db, Experiment, experiment_id)
    if experiment.status not in {"active", "completed"}:
        raise HTTPException(409, "当前实验状态不允许修改幼苗位置标签")
    sample = require_entity(db, SeedlingSample, sample_id)
    dish = require_entity(db, GerminationDish, sample.dish_id)
    material = require_entity(db, ExperimentMaterial, dish.material_id)
    if material.experiment_id != experiment_id:
        raise HTTPException(404, "该实验没有所选幼苗")
    before = {"position_label": sample.position_label}
    sample.position_label = (position_label or "").strip() or None
    after = {"position_label": sample.position_label}
    if before != after:
        record(db, user_id, "update", "SeedlingSample", sample.id, before, after)
        commit_or_conflict(db)
    return {"sample_id": sample.id, **after}
