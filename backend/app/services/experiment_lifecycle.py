from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (Experiment, ExperimentMaterial, ExperimentProtocol, GerminationDish,
                        GerminationObservation, MeasurementTimepoint, SeedlingMeasurement, SeedlingSample)
from app.services.common import commit_or_conflict, record, require_entity
from app.services.local_time import iso_utc
from app.services.measurement_query import summary


def completion_check(db: Session, experiment_id: str):
    experiment = require_entity(db, Experiment, experiment_id)
    dishes = list(db.scalars(select(GerminationDish).join(ExperimentMaterial,
        GerminationDish.material_id == ExperimentMaterial.id).where(ExperimentMaterial.experiment_id == experiment_id)))
    pending = sum(dish.sown_at is None and dish.cancelled_at is None for dish in dishes)
    # A planned duration is not evidence that observation has been completed.
    observing = sum(dish.sown_at is not None and dish.cancelled_at is None for dish in dishes)
    measurement = summary(db, experiment_id)
    outstanding = sum(measurement[key] for key in ("due_today_count", "overdue_count", "upcoming_count", "unschedulable_count"))
    return {"pending_dish_count": pending, "observing_dish_count": observing, **measurement,
            "measurement_pending_count": outstanding,
            "can_complete": experiment.status == "active" and pending == 0 and observing == 0 and outstanding == 0}


def require_complete(db: Session, experiment_id: str):
    result = completion_check(db, experiment_id)
    if not result["can_complete"]:
        raise HTTPException(409, f"实验尚未完成：待置床 {result['pending_dish_count']} 个、仍在观察 {result['observing_dish_count']} 个、幼苗测定 {result['measurement_pending_count']} 项。计划观察天数不代表观察已完成；若决定结束实验，请使用“终止实验”。")


def complete(db: Session, experiment_id: str, user_id: str):
    item = require_entity(db, Experiment, experiment_id)
    require_complete(db, experiment_id)
    before = {"code": item.code, "name": item.name, "status": item.status}
    item.status = "completed"
    item.ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record(db, user_id, "update", "Experiment", item.id, before,
           {**before, "status": item.status, "ended_at": iso_utc(item.ended_at)})
    commit_or_conflict(db)
    return item


def terminate(db: Session, experiment_id: str, reason: str, user_id: str):
    item = require_entity(db, Experiment, experiment_id)
    if item.status != "active":
        raise HTTPException(409, "只有进行中的实验可以终止")
    if not reason.strip():
        raise HTTPException(422, "请填写终止原因，方便以后核对实验履历")
    before = {"code": item.code, "name": item.name, "status": item.status}
    item.status = "cancelled"
    item.termination_reason = reason.strip()
    item.ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
    record(db, user_id, "update", "Experiment", item.id, before,
           {**before, "status": item.status, "termination_reason": item.termination_reason, "ended_at": iso_utc(item.ended_at)})
    commit_or_conflict(db)
    return item


def delete_unused(db: Session, experiment_id: str, user_id: str):
    item = require_entity(db, Experiment, experiment_id)
    material_ids = select(ExperimentMaterial.id).where(ExperimentMaterial.experiment_id == experiment_id)
    dish_ids = select(GerminationDish.id).where(GerminationDish.material_id.in_(material_ids))
    sample_ids = select(SeedlingSample.id).where(SeedlingSample.dish_id.in_(dish_ids))
    has_facts = any(db.scalar(query.limit(1)) is not None for query in (
        select(GerminationDish.id).where(GerminationDish.id.in_(dish_ids), GerminationDish.sown_at.is_not(None)),
        select(GerminationObservation.id).where(GerminationObservation.dish_id.in_(dish_ids)),
        select(SeedlingSample.id).where(SeedlingSample.dish_id.in_(dish_ids)),
        select(SeedlingMeasurement.id).where(SeedlingMeasurement.sample_id.in_(sample_ids))))
    if has_facts:
        raise HTTPException(409, "该实验已经产生实际置床或观测数据，不能永久删除。若实验不再继续，请使用‘终止实验’。")
    if item.status not in {"draft", "ready"}:
        raise HTTPException(409, "已完成或已终止的实验保留历史记录，不能永久删除")
    before = {"code": item.code, "name": item.name, "status": item.status}
    try:
        db.execute(delete(GerminationDish).where(GerminationDish.id.in_(dish_ids)))
        db.execute(delete(MeasurementTimepoint).where(MeasurementTimepoint.experiment_id == item.id))
        db.execute(delete(ExperimentMaterial).where(ExperimentMaterial.experiment_id == item.id))
        db.execute(delete(ExperimentProtocol).where(ExperimentProtocol.experiment_id == item.id))
        record(db, user_id, "delete", "Experiment", item.id, before, None)
        db.delete(item)
        commit_or_conflict(db)
    except Exception:
        db.rollback()
        raise
