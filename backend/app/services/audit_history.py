"""Paginated audit facts with batched business identities, including deleted objects."""
from sqlalchemy import String, case, cast, func, or_, select

from app.models import (AuditLog, Experiment, ExperimentMaterial, ExperimentProtocol, GerminationDish,
    GerminationObservation, MeasurementTimepoint, SeedlingMeasurement, SeedlingSample, SeedLot, Taxon, User)
from app.services.local_time import iso_utc
from app.services.ordering import display_number, field_number, sample_display_number, field_number_expression

LABELS = {"Taxon": "物种", "SeedLot": "种子批次", "Experiment": "实验", "ExperimentProtocol": "实验方案",
          "ExperimentMaterial": "实验材料", "MeasurementTimepoint": "发芽后测定时间", "GerminationDish": "培养皿",
          "GerminationObservation": "发芽巡检", "SeedlingSample": "幼苗", "SeedlingMeasurement": "幼苗测定",
          "User": "账号", "ImportJob": "材料导入", "ExperimentMaterialOrder": "材料顺序"}


def list_history(db, page=1, page_size=50, action=None, entity_type=None, q=None):
    query = select(AuditLog, User.display_name).outerjoin(User, User.id == AuditLog.user_id)
    if action: query = query.where(AuditLog.action == action)
    if entity_type: query = query.where(AuditLog.entity_type == entity_type)
    if q and q.strip():
        term = f"%{q.strip()}%"
        from app.services.measurement_query import slots, search
        c = slots().c
        related_samples = select(c.sample_id).where(or_(search(c, q), c.experiment_code.ilike(term)))
        related_measurements = select(c.measurement_id).where(or_(search(c, q), c.experiment_code.ilike(term)))
        experiment_ids = select(Experiment.id).where(or_(Experiment.code.ilike(term), Experiment.name.ilike(term)))
        material_ids = select(ExperimentMaterial.id).join(SeedLot).join(Taxon).where(or_(
            ExperimentMaterial.experiment_id.in_(experiment_ids), Taxon.common_name.ilike(term),
            Taxon.scientific_name.ilike(term), func.printf("%03d", ExperimentMaterial.experiment_number).ilike(term)))
        replicates = select(GerminationDish.material_id.label("material_id"),
                            func.max(GerminationDish.replicate_no).label("count")).group_by(
                            GerminationDish.material_id).subquery()
        dish_number = field_number_expression(ExperimentMaterial.experiment_number,
                                             GerminationDish.replicate_no, replicates.c.count)
        dish_ids = select(GerminationDish.id).join(ExperimentMaterial).join(
            replicates, replicates.c.material_id == GerminationDish.material_id).where(or_(
            GerminationDish.material_id.in_(material_ids), dish_number.ilike(term)))
        observation_ids = select(GerminationObservation.id).where(GerminationObservation.dish_id.in_(dish_ids))
        protocol_ids = select(ExperimentProtocol.id).where(ExperimentProtocol.experiment_id.in_(experiment_ids))
        def searchable_state(column):
            return cast(case((AuditLog.entity_type == "GerminationDish", func.json_remove(column, "$.code")),
                             else_=column), String).ilike(term)
        query = query.where(or_(searchable_state(AuditLog.before), searchable_state(AuditLog.after),
            User.display_name.ilike(term), AuditLog.entity_type.in_([key for key, value in LABELS.items() if q.strip() in value]),
            AuditLog.entity_id.in_(related_measurements), AuditLog.entity_id.in_(experiment_ids),
            AuditLog.entity_id.in_(material_ids), AuditLog.entity_id.in_(dish_ids), AuditLog.entity_id.in_(observation_ids),
            AuditLog.entity_id.in_(protocol_ids),
            func.json_extract(AuditLog.before, "$.dish_id").in_(dish_ids),
            func.json_extract(AuditLog.after, "$.dish_id").in_(dish_ids),
            func.json_extract(AuditLog.before, "$.sample_id").in_(related_samples),
            func.json_extract(AuditLog.after, "$.sample_id").in_(related_samples)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
    def load(model, ids):
        requested = set(ids) - {None, ""}
        result = {item.id: item for item in db.scalars(select(model).where(model.id.in_(requested)))} if requested else {}
        return result
    ids = lambda name: [log.entity_id for log, _ in rows if log.entity_type == name]
    states = [(log.after or log.before or {}) for log, _ in rows]
    measurements = load(SeedlingMeasurement, ids("SeedlingMeasurement"))
    observations = load(GerminationObservation, ids("GerminationObservation"))
    samples = load(SeedlingSample, ids("SeedlingSample") + [v.sample_id for v in measurements.values()] + [state.get("sample_id") for state in states])
    dishes = load(GerminationDish, ids("GerminationDish") + [s.dish_id for s in samples.values()] +
                  [v.dish_id for v in observations.values()] + [state.get("dish_id") for state in states])
    materials = load(ExperimentMaterial, ids("ExperimentMaterial") + [dish.material_id for dish in dishes.values()])
    protocols = load(ExperimentProtocol, ids("ExperimentProtocol"))
    points = load(MeasurementTimepoint, ids("MeasurementTimepoint") + [v.timepoint_id for v in measurements.values()] + [state.get("timepoint_id") for state in states])
    experiments = load(Experiment, ids("Experiment") + ids("MeasurementTimepoint") +
        [m.experiment_id for m in materials.values()] + [p.experiment_id for p in protocols.values()] + [p.experiment_id for p in points.values()])
    lots = load(SeedLot, ids("SeedLot") + [m.seed_lot_id for m in materials.values()])
    taxa = load(Taxon, ids("Taxon") + [lot.taxon_id for lot in lots.values()])
    replicate_counts = dict(db.execute(select(GerminationDish.material_id, func.max(GerminationDish.replicate_no)).where(
        GerminationDish.material_id.in_(materials)).group_by(GerminationDish.material_id)).all()) if materials else {}
    def subject(log):
        state = log.after or log.before or {}
        entity = log.entity_type
        if entity == "Taxon":
            item = taxa.get(log.entity_id)
            return f"{item.code if item else state.get('code', '')} · {(item.common_name or item.scientific_name) if item else (state.get('common_name') or state.get('scientific_name') or '物种')}"
        if entity == "SeedLot":
            lot = lots.get(log.entity_id)
            taxon = taxa.get(lot.taxon_id) if lot else None
            return f"{lot.code if lot else state.get('code', '')} · {(taxon.common_name or taxon.scientific_name) if taxon else '种子批次'}"
        if entity == "User": return state.get("display_name") or state.get("username") or "账号管理"
        if entity == "ImportJob": return state.get("filename") or "材料导入"
        sample = samples.get(state.get("sample_id")) if entity == "SeedlingMeasurement" else samples.get(log.entity_id) if entity == "SeedlingSample" else None
        measurement = measurements.get(log.entity_id)
        if measurement: sample = samples.get(measurement.sample_id)
        observation = observations.get(log.entity_id)
        dish = dishes.get(sample.dish_id) if sample else dishes.get(observation.dish_id) if observation else dishes.get(log.entity_id) if entity == "GerminationDish" else dishes.get(state.get("dish_id"))
        material = materials.get(dish.material_id) if dish else materials.get(log.entity_id)
        point = points.get(measurement.timepoint_id) if measurement else points.get(state.get("timepoint_id")) or points.get(log.entity_id)
        protocol = protocols.get(log.entity_id)
        experiment = experiments.get(material.experiment_id) if material else experiments.get(point.experiment_id) if point else experiments.get(protocol.experiment_id) if protocol else experiments.get(log.entity_id)
        code = experiment.code if experiment else ("实验履历" if entity == "GerminationDish" else state.get("code", "实验履历"))
        if dish and material:
            number = field_number(material, replicate_counts.get(material.id, 1), dish.replicate_no) or "编号未确认"
            label = f"{code} · {number}"
            if sample:
                number = sample_display_number(material.experiment_number, dish.replicate_no,
                                               replicate_counts.get(material.id, 1), sample.sample_number)
                label = f"{code} · 幼苗 {number or '编号未确认'}"
            if entity == "SeedlingMeasurement" and point: label += f" · DAG{point.day_after_germination}"
            if entity == "GerminationObservation": label += " · 发芽巡检"
            return label
        if material: return f"{code} · {display_number(material.experiment_number) if material.experiment_number else '实验材料'}"
        return f"{code} · {experiment.name if experiment else state.get('name', LABELS.get(entity, '相关数据'))}"
    return {"items": [{"id": log.id, "action": log.action, "entity_type": log.entity_type,
        "entity_label": LABELS.get(log.entity_type, "相关数据"), "subject_label": subject(log),
        "user_display_name": name or "服务器维护", "created_at": iso_utc(log.created_at),
        "before": log.before, "after": log.after} for log, name in rows],
        "total": total, "page": page, "page_size": page_size, "total_pages": (total+page_size-1)//page_size}
