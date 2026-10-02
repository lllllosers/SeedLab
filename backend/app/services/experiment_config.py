"""Experiment design rules. No execution records are created in Stage 1."""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ConfiguredExperimentInput, MaterialInput, MaterialPatch, ProtocolInput
from app.models import Experiment, ExperimentMaterial, ExperimentProtocol, GerminationDish, MeasurementTimepoint, SeedLot, Taxon, User
from app.services.common import commit_or_conflict, flush_or_conflict, record, require_entity
from app.services.experiment_identity import next_experiment_code, experiment_batch_month
from app.api.schemas import ExperimentOut
from app.services.ordering import material_key


def editable(experiment: Experiment) -> None:
    if experiment.numbering_locked_at:
        raise HTTPException(409, "置床编号已确认；尚未置床时可先选择“重新调整实验”")
    if experiment.status not in {"draft", "ready"}:
        raise HTTPException(409, "实验已经开始或结束，不能再修改材料、重复数和测定时间")


def protocol_for(db: Session, experiment_id: str) -> ExperimentProtocol | None:
    return db.scalar(select(ExperimentProtocol).where(ExperimentProtocol.experiment_id == experiment_id))


def materials_for(db: Session, experiment_id: str) -> list[ExperimentMaterial]:
    rows = db.execute(select(ExperimentMaterial, SeedLot, Taxon)
                      .join(SeedLot, ExperimentMaterial.seed_lot_id == SeedLot.id)
                      .join(Taxon, SeedLot.taxon_id == Taxon.id)
                      .where(ExperimentMaterial.experiment_id == experiment_id)).all()
    return [material for material, lot, taxon in sorted(rows, key=lambda row: material_key(row[2], row[1]))]


def days_for(db: Session, experiment_id: str) -> list[MeasurementTimepoint]:
    return list(db.scalars(select(MeasurementTimepoint).where(MeasurementTimepoint.experiment_id == experiment_id)
                           .order_by(MeasurementTimepoint.day_after_germination)))


def normalize_days(days: list[int]) -> list[int]:
    if any(isinstance(day, bool) or not isinstance(day, int) or day < 0 for day in days):
        raise HTTPException(422, "DAG 必须是大于或等于 0 的整数")
    if len(days) != len(set(days)):
        raise HTTPException(422, "同一实验不能设置重复的 DAG 时间点")
    return sorted(days)


def effective(material: ExperimentMaterial | MaterialInput, protocol: ExperimentProtocol | ProtocolInput) -> dict:
    values = {
        "effective_seeds_per_dish": material.seeds_per_dish_override or protocol.seeds_per_dish,
        "effective_replicate_count": material.replicate_count_override or protocol.replicate_count,
        "effective_sample_count": material.sample_count_override or protocol.sample_count,
    }
    if any(value is None or value <= 0 for value in values.values()):
        raise HTTPException(422, "请先填写完整且大于 0 的默认实验方案")
    capacity = values["effective_seeds_per_dish"]
    if protocol.sample_scope == "per_material":
        capacity *= values["effective_replicate_count"]
    if values["effective_sample_count"] > capacity:
        scope = "每个培养皿" if protocol.sample_scope == "per_dish" else "每个实验材料"
        raise HTTPException(422, f"{scope}的取样数不能超过理论可取样种子数 {capacity}")
    return values


def validate_all(protocol: ExperimentProtocol | ProtocolInput, materials: list[ExperimentMaterial | MaterialInput]) -> None:
    if not protocol or any(getattr(protocol, key) is None for key in (
        "seeds_per_dish", "replicate_count", "observation_period_days", "sampling_rule",
        "sample_count", "sample_scope", "germination_criterion"
    )):
        raise HTTPException(422, "请先填写完整的默认实验方案")
    if protocol.sampling_rule != "first_germinated":
        raise HTTPException(422, "当前仅支持按发芽顺序取前 N 株")
    if protocol.sample_scope not in {"per_dish", "per_material"}:
        raise HTTPException(422, "取样范围无效")
    if not protocol.germination_criterion.strip():
        raise HTTPException(422, "请填写发芽判定标准")
    for material in materials:
        effective(material, protocol)


def workload(experiment: Experiment | ConfiguredExperimentInput, protocol: ExperimentProtocol | ProtocolInput,
             materials: list[ExperimentMaterial | MaterialInput], days: list[int]) -> dict:
    validate_all(protocol, materials)
    dishes = seeds = samples = 0
    for material in materials:
        value = effective(material, protocol)
        repeats = value["effective_replicate_count"]
        dishes += repeats
        seeds += repeats * value["effective_seeds_per_dish"]
        samples += value["effective_sample_count"] * (repeats if protocol.sample_scope == "per_dish" else 1)
    start = experiment.planned_start_date
    finish = start + timedelta(days=protocol.observation_period_days + max(days)) if start and days else None
    return {
        "material_count": len(materials), "estimated_dish_count": dishes,
        "estimated_seed_count": seeds, "estimated_sample_count": samples,
        "estimated_measurement_count": samples * len(days),
        "estimated_latest_finish_date": finish,
    }


def validate_lot(db: Session, lot_id: str) -> SeedLot:
    lot = require_entity(db, SeedLot, lot_id)
    if not lot.is_active:
        raise HTTPException(422, f"种子批次 {lot.code} 已停用，不能加入实验")
    return lot


def material_dict(db: Session, material: ExperimentMaterial, protocol: ExperimentProtocol | None) -> dict:
    lot = require_entity(db, SeedLot, material.seed_lot_id)
    taxon = require_entity(db, Taxon, lot.taxon_id)
    result = {
        "id": material.id, "seed_lot_id": material.seed_lot_id, "seed_lot_code": lot.code,
        "taxon_id": taxon.id, "taxon_common_name": taxon.common_name,
        "taxon_scientific_name": taxon.scientific_name, "taxon_code": taxon.code,
        "source_code": lot.source_code, "source": lot.source, "collected_at": lot.collected_at,
        "quantity": lot.quantity, "notes": lot.notes,
        "label": material.label, "display_order": material.display_order,
        "experiment_number": material.experiment_number,
        "seeds_per_dish_override": material.seeds_per_dish_override,
        "replicate_count_override": material.replicate_count_override,
        "sample_count_override": material.sample_count_override,
    }
    if protocol and all(getattr(protocol, key) is not None for key in ("seeds_per_dish", "replicate_count", "sample_count", "sample_scope")):
        result.update(effective(material, protocol))
    else:
        result.update({"effective_seeds_per_dish": None, "effective_replicate_count": None,
                       "effective_sample_count": None})
    return result


def configuration(db: Session, experiment_id: str) -> dict:
    experiment = require_entity(db, Experiment, experiment_id)
    protocol = protocol_for(db, experiment_id)
    materials = materials_for(db, experiment_id)
    days = [item.day_after_germination for item in days_for(db, experiment_id)]
    complete = protocol and all(getattr(protocol, key) is not None for key in (
        "seeds_per_dish", "replicate_count", "observation_period_days", "sampling_rule",
        "sample_count", "sample_scope", "germination_criterion"))
    estimate = workload(experiment, protocol, materials, days) if complete and materials else None
    owner = db.get(User, experiment.owner_id) if experiment.owner_id else None
    return {
        "experiment": ExperimentOut.model_validate(experiment), "protocol": protocol,
        "owner_name": owner.display_name if owner else None,
        "materials": [{**material_dict(db, item, protocol), "preview_number": index}
                      for index, item in enumerate(materials, start=1)],
        "dag_days": days, "workload": estimate,
    }


def preview(data: ConfiguredExperimentInput, db: Session) -> dict:
    if len(data.name.strip()) < 2:
        raise HTTPException(422, "实验名称至少需要 2 个字符")
    normalize_days(data.dag_days)
    if len({item.seed_lot_id for item in data.materials}) != len(data.materials):
        raise HTTPException(422, "同一种子批次不能重复加入实验")
    for item in data.materials:
        validate_lot(db, item.seed_lot_id)
    return workload(data, data.protocol, data.materials, data.dag_days)


def create_configured(db: Session, data: ConfiguredExperimentInput, user_id: str) -> dict:
    preview(data, db)
    experiment = Experiment(code=next_experiment_code(db, data.experiment_type, experiment_batch_month(data.planned_start_date)),
                            experiment_type=data.experiment_type,
                            name=data.name.strip(), description=data.description, planned_start_date=data.planned_start_date,
                            owner_id=user_id)
    db.add(experiment)
    flush_or_conflict(db)
    protocol = ExperimentProtocol(experiment_id=experiment.id, **data.protocol.model_dump())
    db.add(protocol)
    for order, material in enumerate(data.materials):
        db.add(ExperimentMaterial(experiment_id=experiment.id, display_order=order, **material.model_dump()))
    for day in normalize_days(data.dag_days):
        db.add(MeasurementTimepoint(experiment_id=experiment.id, day_after_germination=day))
    flush_or_conflict(db)
    result = configuration(db, experiment.id)
    record(db, user_id, "create", "Experiment", experiment.id, None,
           {"code": experiment.code, "configuration": data.model_dump(mode="json")})
    commit_or_conflict(db)
    return result


def put_protocol(db: Session, experiment_id: str, data: ProtocolInput, user_id: str) -> dict:
    editable(require_entity(db, Experiment, experiment_id))
    material_items = materials_for(db, experiment_id)
    validate_all(data, material_items)
    item = protocol_for(db, experiment_id)
    before = {key: getattr(item, key) for key in ProtocolInput.model_fields} if item else None
    if item is None:
        item = ExperimentProtocol(experiment_id=experiment_id)
        db.add(item)
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    flush_or_conflict(db)
    after = data.model_dump()
    record(db, user_id, "update" if before else "create", "ExperimentProtocol", item.id, before, after)
    commit_or_conflict(db)
    return after


def add_material(db: Session, experiment_id: str, data: MaterialInput, user_id: str) -> dict:
    editable(require_entity(db, Experiment, experiment_id))
    validate_lot(db, data.seed_lot_id)
    current = materials_for(db, experiment_id)
    if any(item.seed_lot_id == data.seed_lot_id for item in current):
        raise HTTPException(409, "该种子批次已加入本实验")
    protocol = protocol_for(db, experiment_id)
    if protocol:
        validate_all(protocol, [data])
    item = ExperimentMaterial(experiment_id=experiment_id, display_order=len(current), **data.model_dump())
    db.add(item)
    flush_or_conflict(db)
    result = material_dict(db, item, protocol)
    record(db, user_id, "create", "ExperimentMaterial", item.id, None, result)
    commit_or_conflict(db)
    return result


def update_material(db: Session, experiment_id: str, material_id: str, data: MaterialPatch, user_id: str) -> dict:
    editable(require_entity(db, Experiment, experiment_id))
    item = require_entity(db, ExperimentMaterial, material_id)
    if item.experiment_id != experiment_id:
        raise HTTPException(404, "实验材料不存在")
    protocol = protocol_for(db, experiment_id)
    before = material_dict(db, item, protocol)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    if protocol:
        validate_all(protocol, [item])
    flush_or_conflict(db)
    after = material_dict(db, item, protocol)
    record(db, user_id, "update", "ExperimentMaterial", item.id, before, after)
    commit_or_conflict(db)
    return after


def remove_material(db: Session, experiment_id: str, material_id: str, user_id: str) -> None:
    experiment = require_entity(db, Experiment, experiment_id)
    editable(experiment)
    item = require_entity(db, ExperimentMaterial, material_id)
    if item.experiment_id != experiment_id:
        raise HTTPException(404, "实验材料不存在")
    if experiment.status == "ready" and len(materials_for(db, experiment_id)) == 1:
        raise HTTPException(422, "已就绪实验必须保留至少一个材料；可先改回草稿")
    if db.scalar(select(GerminationDish.id).where(GerminationDish.material_id == item.id).limit(1)):
        raise HTTPException(409, "该材料已有执行数据，不能移除")
    before = material_dict(db, item, protocol_for(db, experiment_id))
    db.delete(item)
    for order, other in enumerate(material for material in materials_for(db, experiment_id) if material.id != item.id):
        other.display_order = order
    record(db, user_id, "delete", "ExperimentMaterial", item.id, before, None)
    commit_or_conflict(db)


def reorder_materials(db: Session, experiment_id: str, material_ids: list[str], user_id: str) -> list[dict]:
    raise HTTPException(409, "实验材料已按中文名自动排序，不能手动调整顺序")


def replace_days(db: Session, experiment_id: str, days: list[int], user_id: str) -> list[int]:
    experiment = require_entity(db, Experiment, experiment_id)
    editable(experiment)
    normalized = normalize_days(days)
    if experiment.status == "ready" and not normalized:
        raise HTTPException(422, "已就绪实验必须保留至少一个 DAG 时间点；可先改回草稿")
    old = days_for(db, experiment_id)
    before = [item.day_after_germination for item in old]
    if before == normalized:
        return normalized
    existing = {item.day_after_germination: item for item in old}
    for item in old:
        if item.day_after_germination not in normalized:
            db.delete(item)
    for day in normalized:
        if day not in existing:
            db.add(MeasurementTimepoint(experiment_id=experiment_id, day_after_germination=day))
    flush_or_conflict(db)
    record(db, user_id, "update", "MeasurementTimepoint", experiment_id,
           {"dag_days": before}, {"dag_days": normalized})
    commit_or_conflict(db)
    return normalized


def set_status(db: Session, experiment: Experiment, target: str) -> None:
    if target == "completed" and target != experiment.status:
        from app.services.experiment_lifecycle import require_complete
        require_complete(db, experiment.id)
    if target == "cancelled" and target != experiment.status:
        raise HTTPException(409, "请通过“终止实验”填写原因后结束进行中的实验")
    if experiment.numbering_locked_at and target == "draft":
        raise HTTPException(409, "置床编号已确认；若尚未置床，请使用“重新调整实验”")
    allowed = {"draft": {"ready", "cancelled"}, "ready": {"draft", "cancelled"},
               "active": {"completed", "cancelled"}, "completed": set(), "cancelled": set()}
    if target == experiment.status:
        return
    if target not in allowed[experiment.status]:
        raise HTTPException(409, "当前实验不能直接进入该状态，请先完成实验配置并正式开始实验")
    if target in {"ready", "active"}:
        protocol = protocol_for(db, experiment.id)
        materials = materials_for(db, experiment.id)
        days = days_for(db, experiment.id)
        missing = []
        if protocol is None:
            missing.append("填写默认实验方案")
        else:
            fields = {
                "seeds_per_dish": "每皿种子数", "replicate_count": "重复数",
                "observation_period_days": "观察周期", "sampling_rule": "取样方式",
                "sample_count": "取样数", "sample_scope": "取样范围",
                "germination_criterion": "发芽判定标准",
            }
            missing.extend(f"填写{label}" for key, label in fields.items()
                           if not getattr(protocol, key))
        if not materials:
            missing.append("添加至少一个实验材料")
        if not days:
            missing.append("设置至少一个发芽后测定时间（DAG）")
        if missing:
            raise HTTPException(422, "标记为已就绪前，请先" + "、".join(missing))
        validate_all(protocol, materials)
    experiment.status = target
