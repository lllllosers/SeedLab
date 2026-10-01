"""Atomic experiment start, germination observations, and first-N sampling."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import BatchObservationInput, ObservationPatch
from app.models import (Experiment, ExperimentMaterial, GerminationDish, GerminationObservation,
                        SeedlingSample, SeedLot, Taxon)
from app.services.common import commit_or_conflict, flush_or_conflict, record, require_entity
from app.services.experiment_config import days_for, effective, materials_for, protocol_for
from app.services.ordering import field_number
from app.services.local_time import iso_utc, local_date, today, utc_naive


def dishes_for(db: Session, experiment_id: str) -> list[GerminationDish]:
    return list(db.scalars(select(GerminationDish).join(ExperimentMaterial, GerminationDish.material_id == ExperimentMaterial.id)
                           .where(ExperimentMaterial.experiment_id == experiment_id)
                           .order_by(ExperimentMaterial.display_order, GerminationDish.replicate_no)))


def cumulative(db: Session, dish_id: str) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(GerminationObservation.new_germinated_count), 0))
                         .where(GerminationObservation.dish_id == dish_id)) or 0)


def observation_snapshot(observation: GerminationObservation) -> dict:
    return {"id": observation.id, "dish_id": observation.dish_id,
            "observed_at": iso_utc(observation.observed_at),
            "new_germinated_count": observation.new_germinated_count, "notes": observation.notes}


def reconcile_samples(db: Session, material: ExperimentMaterial, user_id: str) -> None:
    """Fill first-N slots in stable observation order without deleting sample identities."""
    protocol = protocol_for(db, material.experiment_id)
    if protocol is None:
        raise HTTPException(422, "请先填写实验方案，再记录发芽巡检")
    target = effective(material, protocol)["effective_sample_count"]
    dishes = list(db.scalars(select(GerminationDish).where(GerminationDish.material_id == material.id)
                              .order_by(GerminationDish.replicate_no)))
    dish_by_id = {dish.id: dish for dish in dishes}
    if not dishes:
        return
    observations = list(db.scalars(select(GerminationObservation)
                                   .where(GerminationObservation.dish_id.in_(dish_by_id))))
    observations.sort(key=lambda obs: (utc_naive(obs.observed_at), dish_by_id[obs.dish_id].replicate_no, obs.id))
    samples = list(db.scalars(select(SeedlingSample).where(SeedlingSample.dish_id.in_(dish_by_id))))
    sourced = defaultdict(list)
    legacy_by_dish = defaultdict(int)
    next_number = defaultdict(int)
    for sample in samples:
        next_number[sample.dish_id] = max(next_number[sample.dish_id], sample.sample_number)
        if sample.source_observation_id:
            sourced[sample.source_observation_id].append(sample)
        else:
            legacy_by_dish[sample.dish_id] += 1
    if protocol.sample_scope == "per_material":
        budget = target - sum(legacy_by_dish.values())
        if budget < 0:
            raise HTTPException(409, "既有样本数超过当前材料取样上限")
    else:
        budgets = {dish.id: target - legacy_by_dish[dish.id] for dish in dishes}
        if any(value < 0 for value in budgets.values()):
            raise HTTPException(409, "既有样本数超过当前培养皿取样上限")

    for observation in observations:
        dish = dish_by_id[observation.dish_id]
        if protocol.sample_scope == "per_material":
            desired = min(observation.new_germinated_count, budget)
            budget -= desired
        else:
            desired = min(observation.new_germinated_count, budgets[dish.id])
            budgets[dish.id] -= desired
        existing = len(sourced[observation.id])
        if existing > desired:
            raise HTTPException(409, "此次修改会使已选幼苗不再属于前 N 株；请保留已有样本")
        for _ in range(desired - existing):
            next_number[dish.id] += 1
            sample = SeedlingSample(dish_id=dish.id, sample_number=next_number[dish.id],
                                    germinated_at=observation.observed_at,
                                    source_observation_id=observation.id)
            db.add(sample)
            flush_or_conflict(db)
            record(db, user_id, "create", "SeedlingSample", sample.id, None,
                   {"dish_id": dish.id, "sample_number": sample.sample_number,
                    "germinated_at": iso_utc(sample.germinated_at),
                    "source_observation_id": observation.id})


def batch_create_observations(db: Session, experiment_id: str, data: BatchObservationInput, user_id: str) -> dict:
    try:
        experiment = require_entity(db, Experiment, experiment_id)
        if experiment.status != "active":
            raise HTTPException(409, "只有进行中的实验可以新增发芽巡检")
        observed_at = utc_naive(data.observed_at)
        entries = [entry for entry in data.entries if entry.new_germinated_count is not None]
        if len({entry.dish_id for entry in entries}) != len(entries):
            raise HTTPException(422, "同一批巡检中培养皿不能重复")
        material_ids = set()
        created = []
        for entry in entries:
            dish = require_entity(db, GerminationDish, entry.dish_id)
            material = require_entity(db, ExperimentMaterial, dish.material_id)
            if material.experiment_id != experiment_id:
                raise HTTPException(404, "培养皿不属于当前实验")
            if dish.cancelled_at is not None:
                raise HTTPException(409, "已取消的培养皿不能记录发芽巡检")
            if dish.sown_at is None:
                raise HTTPException(422, f"培养皿 {dish.code} 缺少实际置床时间")
            if observed_at < utc_naive(dish.sown_at):
                raise HTTPException(422, f"培养皿 {dish.code} 的巡检时间不能早于置床时间")
            current = cumulative(db, dish.id)
            if current + entry.new_germinated_count > dish.seed_count:
                raise HTTPException(422, f"培养皿 {dish.code} 已累计发芽 {current} 粒，本次最多还能记录 {dish.seed_count - current} 粒")
            if db.scalar(select(GerminationObservation.id).where(
                    GerminationObservation.dish_id == dish.id,
                    GerminationObservation.observed_at == observed_at)):
                raise HTTPException(409, f"培养皿 {dish.code} 在这个时间已有巡检记录，请修改原记录或选择其他时间")
            observation = GerminationObservation(dish_id=dish.id, observed_at=observed_at,
                                                 new_germinated_count=entry.new_germinated_count,
                                                 notes=entry.notes)
            db.add(observation)
            created.append(observation)
            material_ids.add(material.id)
        flush_or_conflict(db)
        for material_id in sorted(material_ids):
            reconcile_samples(db, require_entity(db, ExperimentMaterial, material_id), user_id)
        for observation in created:
            record(db, user_id, "create", "GerminationObservation", observation.id, None,
                   observation_snapshot(observation))
        commit_or_conflict(db)
    except Exception:
        db.rollback()
        raise
    return {"created": [observation_snapshot(item) for item in created],
            "execution": execution_summary(db, experiment_id)}


def require_observation(db: Session, experiment_id: str, observation_id: str) -> tuple[Experiment, GerminationDish, GerminationObservation]:
    experiment = require_entity(db, Experiment, experiment_id)
    observation = require_entity(db, GerminationObservation, observation_id)
    dish = require_entity(db, GerminationDish, observation.dish_id)
    material = require_entity(db, ExperimentMaterial, dish.material_id)
    if material.experiment_id != experiment_id:
        raise HTTPException(404, "巡检记录不属于当前实验")
    return experiment, dish, observation


def correct_observation(db: Session, experiment_id: str, observation_id: str,
                        data: ObservationPatch, user_id: str) -> dict:
    try:
        experiment, dish, observation = require_observation(db, experiment_id, observation_id)
        if experiment.status not in {"active", "completed"}:
            raise HTTPException(409, "当前实验状态不允许修正巡检记录")
        patch = data.model_dump(exclude_unset=True)
        if "new_germinated_count" in patch and patch["new_germinated_count"] is None:
            raise HTTPException(422, "本次新增发芽数不可为空；0 表示已巡检且无新增")
        before = observation_snapshot(observation)
        if "new_germinated_count" in patch:
            source_count = db.scalar(select(func.count(SeedlingSample.id)).where(
                SeedlingSample.source_observation_id == observation.id)) or 0
            if patch["new_germinated_count"] < source_count:
                raise HTTPException(409, f"此次巡检已选出 {source_count} 株幼苗，本次新增发芽数不能小于 {source_count}")
            other_total = cumulative(db, dish.id) - observation.new_germinated_count
            if other_total + patch["new_germinated_count"] > dish.seed_count:
                raise HTTPException(422, f"培养皿 {dish.code} 的其他巡检已记录 {other_total} 粒，本次最多还能填写 {dish.seed_count - other_total} 粒")
        for key, value in patch.items():
            setattr(observation, key, value)
        flush_or_conflict(db)
        reconcile_samples(db, require_entity(db, ExperimentMaterial, dish.material_id), user_id)
        after = observation_snapshot(observation)
        record(db, user_id, "update", "GerminationObservation", observation.id, before, after)
        commit_or_conflict(db)
    except Exception:
        db.rollback()
        raise
    return after


def delete_observation(db: Session, experiment_id: str, observation_id: str, user_id: str) -> None:
    try:
        experiment, dish, observation = require_observation(db, experiment_id, observation_id)
        if experiment.status not in {"active", "completed"}:
            raise HTTPException(409, "当前实验状态不允许删除巡检记录")
        if db.scalar(select(SeedlingSample.id).where(SeedlingSample.source_observation_id == observation.id).limit(1)):
            raise HTTPException(409, "此次巡检已产生幼苗样本，不能删除")
        before = observation_snapshot(observation)
        db.delete(observation)
        flush_or_conflict(db)
        reconcile_samples(db, require_entity(db, ExperimentMaterial, dish.material_id), user_id)
        record(db, user_id, "delete", "GerminationObservation", observation_id, before, None)
        commit_or_conflict(db)
    except Exception:
        db.rollback()
        raise


def execution_summary(db: Session, experiment_id: str) -> dict:
    experiment = require_entity(db, Experiment, experiment_id)
    protocol = protocol_for(db, experiment_id)
    materials = materials_for(db, experiment_id)
    dishes = dishes_for(db, experiment_id)
    dish_by_id = {dish.id: dish for dish in dishes}
    observations = list(db.scalars(select(GerminationObservation).where(
        GerminationObservation.dish_id.in_(dish_by_id)))) if dishes else []
    samples = list(db.scalars(select(SeedlingSample).where(
        SeedlingSample.dish_id.in_(dish_by_id)))) if dishes else []
    observations_by_dish = defaultdict(list)
    samples_by_dish = defaultdict(list)
    samples_by_source = defaultdict(int)
    for observation in observations:
        observations_by_dish[observation.dish_id].append(observation)
    for sample in samples:
        samples_by_dish[sample.dish_id].append(sample)
        if sample.source_observation_id:
            samples_by_source[sample.source_observation_id] += 1
    material_rows = []
    dish_rows = []
    local_today = today()
    for preview_number, material in enumerate(materials, start=1):
        lot = require_entity(db, SeedLot, material.seed_lot_id)
        taxon = require_entity(db, Taxon, lot.taxon_id)
        relevant = [dish for dish in dishes if dish.material_id == material.id]
        material_samples = sum(len(samples_by_dish[dish.id]) for dish in relevant)
        has_defaults = protocol and all(getattr(protocol, key) is not None for key in (
            "seeds_per_dish", "replicate_count", "sample_count", "sample_scope"))
        values = effective(material, protocol) if has_defaults else None
        material_seed_total = material_germinated = 0
        replicate_count = values["effective_replicate_count"] if values else len(relevant)
        for dish in relevant:
            history = observations_by_dish[dish.id]
            germinated = sum(item.new_germinated_count for item in history)
            if dish.sown_at and not dish.cancelled_at:
                material_seed_total += dish.seed_count
            material_germinated += germinated
            dish_rows.append({
                "id": dish.id, "code": dish.code, "material_id": material.id,
                "taxon_common_name": taxon.common_name, "taxon_scientific_name": taxon.scientific_name,
                "taxon_code": taxon.code, "seed_lot_code": lot.code,
                "source_code": lot.source_code,
                "experiment_number": material.experiment_number,
                "preview_number": preview_number,
                "field_number": field_number(material, replicate_count, dish.replicate_no) if material.experiment_number else None,
                "replicate_no": dish.replicate_no, "label": dish.label,
                "seed_count": dish.seed_count, "sown_at": iso_utc(dish.sown_at),
                "cancelled_at": iso_utc(dish.cancelled_at), "cancel_reason": dish.cancel_reason,
                "today_observed": any(local_date(item.observed_at) == local_today for item in history),
                "observation_period_end_at": iso_utc(utc_naive(dish.sown_at) + timedelta(days=protocol.observation_period_days))
                  if dish.sown_at and protocol and protocol.observation_period_days else None,
                "cumulative_germinated": germinated,
                "germination_rate": round(germinated / dish.seed_count * 100, 2),
                "remaining_ungerminated": dish.seed_count - germinated,
                "sample_count": len(samples_by_dish[dish.id]),
                "sample_target": values["effective_sample_count"] if values else None,
                "material_sample_count": material_samples,
                "last_observed_at": iso_utc(max((item.observed_at for item in history), default=None)),
                "observation_count": len(history),
            })
        material_rows.append({
            "id": material.id, "taxon_common_name": taxon.common_name,
            "taxon_scientific_name": taxon.scientific_name, "taxon_code": taxon.code,
            "seed_lot_code": lot.code, "source_code": lot.source_code,
            "experiment_number": material.experiment_number, "preview_number": preview_number,
            "sown_count": sum(dish.sown_at is not None for dish in relevant),
            "cancelled_count": sum(dish.cancelled_at is not None for dish in relevant),
            "dish_count": len(relevant), "seed_count": material_seed_total,
            "cumulative_germinated": material_germinated,
            "germination_rate": round(material_germinated / material_seed_total * 100, 2) if material_seed_total else 0,
            "sample_count": material_samples,
            "sample_target": values["effective_sample_count"] * (
                sum(dish.cancelled_at is None for dish in relevant) if protocol.sample_scope == "per_dish" else 1
            ) if values else None,
        })
    observations.sort(key=lambda item: (utc_naive(item.observed_at), dish_by_id[item.dish_id].replicate_no), reverse=True)
    field_by_dish = {row["id"]: row["field_number"] for row in dish_rows}
    recent = [{**observation_snapshot(item), "dish_code": dish_by_id[item.dish_id].code,
               "field_number": field_by_dish[item.dish_id],
               "replicate_no": dish_by_id[item.dish_id].replicate_no,
               "generated_sample_count": samples_by_source[item.id]}
              for item in observations[:100]]
    total_seeds = sum(dish.seed_count for dish in dishes if dish.sown_at and not dish.cancelled_at)
    total_germinated = sum(item.new_germinated_count for item in observations)
    sown_dishes = [dish for dish in dishes if dish.sown_at]
    pending_dishes = [dish for dish in dishes if not dish.sown_at and not dish.cancelled_at]
    period_end = max((utc_naive(dish.sown_at) + timedelta(days=protocol.observation_period_days)
                      for dish in sown_dishes), default=None) if protocol and protocol.observation_period_days else None
    dag_days = [item.day_after_germination for item in days_for(db, experiment_id)]
    latest_finish = period_end + timedelta(days=max(dag_days)) if period_end and dag_days else None
    return {
        "experiment": {"id": experiment.id, "code": experiment.code, "name": experiment.name,
                       "status": experiment.status, "started_at": iso_utc(experiment.started_at),
                       "numbering_locked_at": iso_utc(experiment.numbering_locked_at)},
        "sampling_rule": protocol.sampling_rule if protocol else None,
        "sample_scope": protocol.sample_scope if protocol else None,
        "observation_period_days": protocol.observation_period_days if protocol else None,
        "observation_period_end_at": iso_utc(period_end),
        "observation_period_overdue": bool(period_end and datetime.now(timezone.utc).replace(tzinfo=None) > period_end),
        "dish_count": len(dishes), "seed_count": total_seeds,
        "sown_count": len(sown_dishes), "pending_count": len(pending_dishes),
        "cancelled_count": sum(dish.cancelled_at is not None for dish in dishes),
        "today_observed_count": sum(row["today_observed"] for row in dish_rows if row["sown_at"] and not row["cancelled_at"]),
        "today_pending_count": sum(not row["today_observed"] for row in dish_rows if row["sown_at"] and not row["cancelled_at"] and
                                   (not row["observation_period_end_at"] or datetime.now(timezone.utc) <=
                                    datetime.fromisoformat(row["observation_period_end_at"].replace("Z", "+00:00")))),
        "latest_sown_estimated_finish_at": iso_utc(latest_finish),
        "pending_material_count": sum(any(not dish.sown_at and not dish.cancelled_at for dish in dishes
                                         if dish.material_id == material.id) for material in materials),
        "cumulative_germinated": total_germinated,
        "germination_rate": round(total_germinated / total_seeds * 100, 2) if total_seeds else 0,
        "sample_count": len(samples),
        "materials": material_rows, "dishes": dish_rows, "recent_observations": recent,
    }
