"""Derived DAG work queue and immutable sample identity with auditable measurements."""

from decimal import Decimal, InvalidOperation

from app.contracts.errors import ConflictError, NotFoundError, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.measurement import MeasurementInput, MeasurementPatch
from app.models import (Experiment, ExperimentMaterial, GerminationDish, MeasurementTimepoint,
                        SeedlingMeasurement, SeedlingSample)
from app.services.application_support import commit_or_conflict, flush_or_conflict, record, require_entity
from app.services.local_time import iso_utc, local_date, utc_naive
from app.services.measurement_schedule import scheduled_date


def _measurement_state(item: SeedlingMeasurement) -> dict:
    return {"id": item.id, "sample_id": item.sample_id, "timepoint_id": item.timepoint_id,
            "root_length_mm": float(item.root_length_mm) if item.root_length_mm is not None else None,
            "shoot_length_mm": float(item.shoot_length_mm) if item.shoot_length_mm is not None else None,
            "root_unavailable": item.root_unavailable, "shoot_unavailable": item.shoot_unavailable,
            "measured_at": iso_utc(item.measured_at), "notes": item.notes}


def task_data(db: Session, experiment_id: str, status: str | None = None,
              dag: int | None = None, q: str | None = None, material_id: str | None = None,
              *, current_tasks: bool = True) -> dict:
    # Material history uses the same factual projection without the current-task filter.
    from app.services.measurement_query import slots, slot_summary, task_summary, search, task_row
    from sqlalchemy import case
    experiment = require_entity(db, Experiment, experiment_id)
    if status not in {None, "pending", "due_today", "overdue", "upcoming", "completed", "unschedulable"}:
        raise ValidationError("请选择有效的测定任务状态")
    days = list(db.scalars(select(MeasurementTimepoint.day_after_germination).where(
        MeasurementTimepoint.experiment_id == experiment_id).order_by(MeasurementTimepoint.day_after_germination)))
    if dag is not None and dag not in days:
        raise ValidationError("该实验没有所选的发芽后测定时间")
    c = slots().c
    query = select(c).where(c.experiment_id == experiment_id)
    if current_tasks:
        query = query.where(experiment.status == "active")
    if material_id:
        query = query.where(c.material_id == material_id)
    if status == "pending":
        query = query.where(c.status.in_(["overdue", "due_today"]))
    elif status:
        query = query.where(c.status == status)
    if dag is not None:
        query = query.where(c.day_after_germination == dag)
    if q and q.strip():
        query = query.where(search(c, q))
    priority = case((c.status == "overdue", 0), (c.status == "due_today", 1),
                    (c.status == "upcoming", 2), (c.status == "unschedulable", 3), else_=4)
    rows = db.execute(query.order_by(priority, c.scheduled_date, c.experiment_number,
                                    c.replicate_no, c.sample_number, c.day_after_germination)).mappings()
    return {"experiment_status": experiment.status, "dag_days": days,
            "summary": (task_summary if current_tasks else slot_summary)(db, experiment_id),
            "tasks": [task_row(row) for row in rows]}


def history(db: Session, experiment_id: str, material_id: str) -> dict:
    require_entity(db, Experiment, experiment_id)
    material = require_entity(db, ExperimentMaterial, material_id)
    if material.experiment_id != experiment_id:
        raise NotFoundError("该实验没有所选材料")
    derived = task_data(db, experiment_id, material_id=material_id, current_tasks=False)
    tasks = [item for item in derived["tasks"] if item["material_id"] == material_id]
    samples = {}
    for task in tasks:
        sample = samples.setdefault(task["sample_id"], {"sample_id": task["sample_id"],
            "sample_number": task["sample_number"], "field_number": task["field_number"],
            "sample_display_number": task["sample_display_number"],
            "position_label": task["position_label"], "germinated_at": task["germinated_at"], "measurements": {}})
        sample["measurements"][str(task["day_after_germination"])] = task
    return {"dag_days": derived["dag_days"],
            "samples": sorted(samples.values(), key=lambda row: (row["field_number"] or "", row["sample_number"]))}


def _ownership(db: Session, experiment_id: str, sample_id: str, timepoint_id: str):
    sample = require_entity(db, SeedlingSample, sample_id)
    dish = require_entity(db, GerminationDish, sample.dish_id)
    material = require_entity(db, ExperimentMaterial, dish.material_id)
    point = require_entity(db, MeasurementTimepoint, timepoint_id)
    if material.experiment_id != experiment_id or point.experiment_id != experiment_id:
        raise ValidationError("幼苗与测定时间必须属于当前实验")
    if sample.germinated_at is None:
        raise ValidationError("这株幼苗缺少发芽判定时间，暂时无法安排测定；请先核对历史样本")
    return sample, point


def _validate(values: dict, sample: SeedlingSample, point: MeasurementTimepoint) -> dict:
    for part, label in (("root", "根长"), ("shoot", "苗长")):
        key = f"{part}_length_mm"
        unavailable = values[f"{part}_unavailable"]
        raw = values[key]
        if unavailable is None or (raw is None) == (unavailable is False):
            raise ValidationError(f"{label}请填写非负数值，或选择无法测量")
        if raw is not None:
            try:
                number = Decimal(str(raw))
                if not number.is_finite() or number < 0 or number.as_tuple().exponent < -2 or number > Decimal("99999999.99"):
                    raise ValueError
            except (InvalidOperation, ValueError):
                raise ValidationError(f"{label}请填写不超过两位小数的非负数值") from None
            values[key] = number
    measured = values["measured_at"]
    if measured is None:
        raise ValidationError("请填写实际测定时间")
    planned = scheduled_date(sample.germinated_at, point.day_after_germination)
    if local_date(measured) < planned:
        raise ValidationError(f"该幼苗的 DAG {point.day_after_germination} 计划测定日期为{planned.month}月{planned.day}日，当前测定时间早于计划日期")
    values["measured_at"] = utc_naive(measured)
    return values


def create(db: Session, experiment_id: str, data: MeasurementInput, user_id: str) -> dict:
    experiment = require_entity(db, Experiment, experiment_id)
    if experiment.status != "active":
        raise ConflictError("只有进行中的实验可以新增幼苗测定")
    sample, point = _ownership(db, experiment_id, data.sample_id, data.timepoint_id)
    if db.scalar(select(SeedlingMeasurement.id).where(SeedlingMeasurement.sample_id == sample.id,
                                                     SeedlingMeasurement.timepoint_id == point.id)):
        raise ConflictError("这株幼苗在该发芽后测定时间已有记录，请打开历史记录修改")
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
        raise ConflictError("当前实验状态不允许修改幼苗测定")
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
        raise ConflictError("只有进行中的实验可以清除本阶段测定；已完成实验仍可修改原记录")
    before = _measurement_state(item)
    db.delete(item)
    flush_or_conflict(db)
    record(db, user_id, "delete", "SeedlingMeasurement", measurement_id, before, None)
    commit_or_conflict(db)


def update_position(db: Session, experiment_id: str, sample_id: str,
                    position_label: str | None, user_id: str) -> dict:
    experiment = require_entity(db, Experiment, experiment_id)
    if experiment.status not in {"active", "completed"}:
        raise ConflictError("当前实验状态不允许修改幼苗位置标签")
    sample = require_entity(db, SeedlingSample, sample_id)
    dish = require_entity(db, GerminationDish, sample.dish_id)
    material = require_entity(db, ExperimentMaterial, dish.material_id)
    if material.experiment_id != experiment_id:
        raise NotFoundError("该实验没有所选幼苗")
    before = {"position_label": sample.position_label}
    sample.position_label = (position_label or "").strip() or None
    after = {"position_label": sample.position_label}
    if before != after:
        record(db, user_id, "update", "SeedlingSample", sample.id, before, after)
        commit_or_conflict(db)
    return {"sample_id": sample.id, **after}
