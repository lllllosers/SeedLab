"""Confirm field numbers and record each dish's real sowing time."""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Experiment, ExperimentMaterial, GerminationDish, GerminationObservation
from app.services.common import commit_or_conflict, flush_or_conflict, record, require_entity
from app.services.experiment_config import days_for, effective, materials_for, protocol_for, validate_all
from app.services.germination_execution import dishes_for, execution_summary, iso_utc, utc_naive
from app.services.ordering import display_number, field_number


def confirm_numbers(db: Session, experiment_id: str, user_id: str) -> dict:
    try:
        experiment = require_entity(db, Experiment, experiment_id)
        if experiment.status != "ready" or experiment.numbering_locked_at:
            raise HTTPException(409, "请先将实验标记为已就绪，且不要重复确认置床编号")
        if dishes_for(db, experiment_id):
            raise HTTPException(409, "本实验已有培养皿，不能重复生成编号")
        protocol = protocol_for(db, experiment_id)
        materials = materials_for(db, experiment_id)
        if not materials or not days_for(db, experiment_id):
            raise HTTPException(422, "请先完成实验材料和发芽后测定时间设置")
        validate_all(protocol, materials)
        for number, material in enumerate(materials, start=1):
            material.experiment_number = number
            material.display_order = number - 1
            values = effective(material, protocol)
            for replicate in range(1, values["effective_replicate_count"] + 1):
                dish = GerminationDish(
                    material_id=material.id,
                    code=f"{experiment.code}-M{number:03d}-R{replicate:02d}",
                    replicate_no=replicate, label=f"R{replicate}",
                    seed_count=values["effective_seeds_per_dish"], sown_at=None)
                db.add(dish)
                flush_or_conflict(db)
                record(db, user_id, "create", "GerminationDish", dish.id, None,
                       {"field_number": field_number(material, values["effective_replicate_count"], replicate),
                        "code": dish.code, "planned": True})
        experiment.numbering_locked_at = datetime.now(timezone.utc).replace(tzinfo=None)
        record(db, user_id, "update", "Experiment", experiment.id, {"numbering_locked_at": None},
               {"numbering_locked_at": iso_utc(experiment.numbering_locked_at),
                "material_count": len(materials)})
        commit_or_conflict(db)
    except Exception:
        db.rollback()
        raise
    return execution_summary(db, experiment_id)


def unlock_numbers(db: Session, experiment_id: str, user_id: str) -> dict:
    try:
        experiment = require_entity(db, Experiment, experiment_id)
        if experiment.status != "ready" or not experiment.numbering_locked_at:
            raise HTTPException(409, "只有尚未开始置床的已就绪实验可以重新调整")
        dishes = dishes_for(db, experiment_id)
        if any(dish.sown_at for dish in dishes):
            raise HTTPException(409, "已有培养皿实际置床，现场编号不能重新调整")
        if dishes and db.scalar(select(GerminationObservation.id).where(
                GerminationObservation.dish_id.in_([dish.id for dish in dishes])).limit(1)):
            raise HTTPException(409, "已有发芽巡检，现场编号不能重新调整")
        for dish in dishes:
            db.delete(dish)
        for material in materials_for(db, experiment_id):
            material.experiment_number = None
        experiment.numbering_locked_at = None
        experiment.status = "draft"
        record(db, user_id, "update", "Experiment", experiment.id,
               {"numbering_confirmed": True}, {"numbering_confirmed": False, "status": "draft"})
        commit_or_conflict(db)
    except Exception:
        db.rollback()
        raise
    return execution_summary(db, experiment_id)


def _dish(db: Session, experiment_id: str, dish_id: str) -> GerminationDish:
    dish = require_entity(db, GerminationDish, dish_id)
    material = require_entity(db, ExperimentMaterial, dish.material_id)
    if material.experiment_id != experiment_id:
        raise HTTPException(404, "该培养皿不属于当前实验")
    return dish


def sow_dishes(db: Session, experiment_id: str, dish_ids: list[str], sown_at: datetime,
               user_id: str) -> dict:
    try:
        experiment = require_entity(db, Experiment, experiment_id)
        if experiment.status not in {"ready", "active"} or not experiment.numbering_locked_at:
            raise HTTPException(409, "请先确认置床编号，再登记实际置床时间")
        if not dish_ids or len(dish_ids) != len(set(dish_ids)):
            raise HTTPException(422, "请至少选择一个未重复的培养皿")
        actual = utc_naive(sown_at)
        dishes = [_dish(db, experiment_id, dish_id) for dish_id in dish_ids]
        for dish in dishes:
            if dish.cancelled_at:
                raise HTTPException(409, "已取消的培养皿不能登记置床")
            if dish.sown_at:
                raise HTTPException(409, "所选培养皿中已有置床记录；请使用时间纠错入口")
            dish.sown_at = actual
            record(db, user_id, "update", "GerminationDish", dish.id,
                   {"sown_at": None}, {"sown_at": iso_utc(actual)})
        if experiment.status == "ready":
            experiment.status = "active"
        if experiment.started_at is None or actual < utc_naive(experiment.started_at):
            experiment.started_at = actual
        record(db, user_id, "update", "Experiment", experiment.id, None,
               {"status": experiment.status, "started_at": iso_utc(experiment.started_at)})
        commit_or_conflict(db)
    except Exception:
        db.rollback()
        raise
    return execution_summary(db, experiment_id)


def correct_sowing(db: Session, experiment_id: str, dish_id: str, sown_at: datetime,
                   user_id: str) -> dict:
    try:
        experiment = require_entity(db, Experiment, experiment_id)
        if experiment.status not in {"active", "completed"}:
            raise HTTPException(409, "已终止的实验只供查阅，不能修改置床记录")
        dish = _dish(db, experiment_id, dish_id)
        if not dish.sown_at or dish.cancelled_at:
            raise HTTPException(409, "只有已置床的培养皿可以修改实际置床时间")
        actual = utc_naive(sown_at)
        earliest = db.scalar(select(func.min(GerminationObservation.observed_at)).where(
            GerminationObservation.dish_id == dish.id))
        if earliest and actual > utc_naive(earliest):
            raise HTTPException(422, "置床时间不能晚于该培养皿最早的发芽巡检时间")
        before = iso_utc(dish.sown_at)
        old_start = iso_utc(experiment.started_at)
        dish.sown_at = actual
        all_sown = [item.sown_at for item in dishes_for(db, experiment_id) if item.sown_at]
        experiment.started_at = min(all_sown) if all_sown else None
        record(db, user_id, "update", "GerminationDish", dish.id,
               {"sown_at": before}, {"sown_at": iso_utc(actual)})
        if old_start != iso_utc(experiment.started_at):
            record(db, user_id, "update", "Experiment", experiment.id,
                   {"started_at": old_start}, {"started_at": iso_utc(experiment.started_at)})
        commit_or_conflict(db)
    except Exception:
        db.rollback()
        raise
    return execution_summary(db, experiment_id)


def cancel_dish(db: Session, experiment_id: str, dish_id: str, reason: str,
                user_id: str) -> dict:
    try:
        experiment = require_entity(db, Experiment, experiment_id)
        if experiment.status not in {"ready", "active"}:
            raise HTTPException(409, "当前实验不能取消计划培养皿")
        dish = _dish(db, experiment_id, dish_id)
        if dish.sown_at or dish.cancelled_at:
            raise HTTPException(409, "只有待置床的培养皿可以取消")
        if not reason.strip():
            raise HTTPException(422, "请填写取消原因")
        dish.cancelled_at = datetime.now(timezone.utc).replace(tzinfo=None)
        dish.cancel_reason = reason.strip()
        record(db, user_id, "update", "GerminationDish", dish.id,
               {"status": "planned"}, {"status": "cancelled", "reason": dish.cancel_reason})
        commit_or_conflict(db)
    except Exception:
        db.rollback()
        raise
    return execution_summary(db, experiment_id)
