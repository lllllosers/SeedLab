"""SQLite derives slots and material counts; only requested pages reach Python."""
from datetime import date
import re

from fastapi import HTTPException
from sqlalchemy import Integer, String, and_, case, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models import (Experiment, ExperimentMaterial, GerminationDish, MeasurementTimepoint,
                        SeedlingMeasurement, SeedlingSample, SeedLot, Taxon)
from app.services.common import require_entity
from app.services.local_time import iso_utc, today


def slots():
    s, d, m, lot, t, p, v = SeedlingSample, GerminationDish, ExperimentMaterial, SeedLot, Taxon, MeasurementTimepoint, SeedlingMeasurement
    replicates = select(d.material_id.label("material_id"), func.max(d.replicate_no).label("count")).group_by(d.material_id).subquery()
    number = func.printf("%03d", m.experiment_number)
    field = case((replicates.c.count == 1, number), else_=number + "-" + cast(d.replicate_no, String))
    planned = func.date(func.seedlab_local_date(s.germinated_at), "+" + cast(p.day_after_germination, String) + " days")
    measured_date = func.seedlab_local_date(v.measured_at)
    state = case((v.id.is_not(None), "completed"), (s.germinated_at.is_(None), "unschedulable"),
                 (planned < today().isoformat(), "overdue"), (planned == today().isoformat(), "due_today"), else_="upcoming")
    return select(
        Experiment.id.label("experiment_id"), Experiment.code.label("experiment_code"),
        m.id.label("material_id"), number.label("experiment_number"),
        d.id.label("dish_id"), d.code.label("dish_code"), field.label("field_number"), d.replicate_no,
        s.id.label("sample_id"), s.sample_number, s.position_label, s.germinated_at,
        t.common_name.label("taxon_common_name"), t.scientific_name.label("taxon_scientific_name"), t.code.label("taxon_code"),
        lot.code.label("seed_lot_code"), lot.source_code,
        p.id.label("timepoint_id"), p.day_after_germination,
        planned.label("scheduled_date"), state.label("status"), v.id.label("measurement_id"),
        v.root_length_mm, v.shoot_length_mm, v.root_unavailable, v.shoot_unavailable, v.measured_at, v.notes,
        measured_date.label("measured_date"),
        cast(func.julianday(measured_date) - func.julianday(planned), Integer).label("delay_days")
    ).select_from(s).join(d, s.dish_id == d.id).join(m, d.material_id == m.id).join(Experiment, m.experiment_id == Experiment.id).join(
        lot, m.seed_lot_id == lot.id).join(t, lot.taxon_id == t.id).join(p, p.experiment_id == m.experiment_id).join(
        replicates, replicates.c.material_id == m.id).outerjoin(v, and_(v.sample_id == s.id, v.timepoint_id == p.id)).subquery()


def counts(c):
    return [func.sum(case((c.status == state, 1), else_=0)).label(f"{state}_count")
            for state in ("due_today", "overdue", "upcoming", "unschedulable")] + [
        func.sum(case((and_(c.status == "completed", c.measured_date == today().isoformat()), 1), else_=0)).label("completed_today_count"),
        func.sum(case((c.status.in_(["overdue", "due_today"]), 1), else_=0)).label("pending_count")]


def summary(db: Session, experiment_id: str) -> dict:
    c = slots().c
    row = db.execute(select(*counts(c), func.count(func.distinct(case((c.status.in_(["overdue", "due_today"]), c.material_id)))).label("material_count"))
                     .where(c.experiment_id == experiment_id)).mappings().one()
    return {key: value or 0 for key, value in row.items()}


def search(c, q: str | None):
    normalized = (q or '').strip()
    if re.fullmatch(r"\d{3}", normalized):
        return c.experiment_number == normalized
    if re.fullmatch(r"\d{3}-\d+", normalized):
        return c.field_number == normalized
    term = f"%{normalized}%"
    return or_(*(column.ilike(term) for column in (c.experiment_number, c.field_number, c.dish_code,
        c.taxon_common_name, c.taxon_scientific_name, c.taxon_code, c.seed_lot_code, c.source_code,
        c.position_label, cast(c.sample_number, String), "幼苗" + func.printf("%02d", c.sample_number),
        "幼苗 " + func.printf("%02d", c.sample_number))))


def task_row(row) -> dict:
    item = dict(row)
    item.pop("measured_date", None)
    for key in ("germinated_at", "measured_at"):
        item[key] = iso_utc(item[key])
    for key in ("root_length_mm", "shoot_length_mm"):
        item[key] = float(item[key]) if item[key] is not None else None
    for key in ("root_unavailable", "shoot_unavailable"):
        item[key] = bool(item[key])
    return item


def worklist(db: Session, experiment_id: str, status="pending", dag=None, q=None, page=1, page_size=25):
    experiment = require_entity(db, Experiment, experiment_id)
    c = slots().c
    filters = [c.experiment_id == experiment_id]
    if dag is not None:
        filters.append(c.day_after_germination == dag)
    if q and q.strip():
        filters.append(search(c, q))
    grouped = select(c.material_id, c.experiment_number, c.taxon_common_name.label("common_name"),
        c.taxon_scientific_name.label("scientific_name"), *counts(c)).where(*filters).group_by(
        c.material_id, c.experiment_number, c.taxon_common_name, c.taxon_scientific_name).subquery()
    a = grouped.c
    having = {"pending": a.pending_count > 0, "overdue": a.overdue_count > 0, "due_today": a.due_today_count > 0,
              "all": a.material_id.is_not(None)}
    if status not in having:
        raise HTTPException(422, "请选择有效的材料任务状态")
    query = select(grouped).where(having[status])
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    materials = [dict(row) for row in db.execute(query.order_by(case((a.overdue_count > 0, 0), (a.due_today_count > 0, 1), else_=2),
        a.experiment_number, a.material_id).offset((page - 1) * page_size).limit(page_size)).mappings()]
    ids = [row["material_id"] for row in materials]
    dag_counts = db.execute(select(c.material_id, c.day_after_germination, *counts(c)).where(
        c.experiment_id == experiment_id, c.material_id.in_(ids)).group_by(c.material_id, c.day_after_germination)).mappings().all() if ids else []
    for material in materials:
        material["dag_counts"] = [{key: value for key, value in row.items() if key != "material_id"}
                                  for row in dag_counts if row["material_id"] == material["material_id"]]
    return {"experiment_status": experiment.status, "summary": summary(db, experiment_id),
            "dag_days": list(db.scalars(select(MeasurementTimepoint.day_after_germination).where(MeasurementTimepoint.experiment_id == experiment_id).order_by(MeasurementTimepoint.day_after_germination))),
            "materials": materials, "page": page, "page_size": page_size, "total_materials": total,
            "total_pages": (total + page_size - 1) // page_size}


def records(db: Session, experiment_id: str, q=None, material_ids=None, dag=None,
            date_from: date | None = None, date_to: date | None = None, page=1, page_size=50):
    require_entity(db, Experiment, experiment_id)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "开始日期不能晚于结束日期")
    c = slots().c
    filters = [c.experiment_id == experiment_id, c.measurement_id.is_not(None)]
    if q and q.strip(): filters.append(search(c, q))
    if material_ids: filters.append(c.material_id.in_(material_ids))
    if dag is not None: filters.append(c.day_after_germination == dag)
    if date_from: filters.append(c.measured_date >= date_from.isoformat())
    if date_to: filters.append(c.measured_date <= date_to.isoformat())
    query = select(c).where(*filters)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.execute(query.order_by(c.measured_at.desc(), c.experiment_number, c.sample_number, c.day_after_germination)
                      .offset((page - 1) * page_size).limit(page_size)).mappings()
    return {"items": [task_row(row) for row in rows], "page": page, "page_size": page_size,
            "total": total, "total_pages": (total + page_size - 1) // page_size}


def dashboard(db: Session):
    source = slots()
    c = source.c
    rows = db.execute(select(Experiment.id, Experiment.code, Experiment.name, *counts(c),
        func.count(func.distinct(case((c.status.in_(["overdue", "due_today"]), c.material_id)))).label("material_count"))
        .join(source, c.experiment_id == Experiment.id).where(Experiment.status == "active").group_by(Experiment.id)
        .having(func.sum(case((c.status.in_(["overdue", "due_today"]), 1), else_=0)) > 0)
        .order_by(Experiment.code)).mappings().all()
    return {"due_today_count": sum(row["due_today_count"] for row in rows), "overdue_count": sum(row["overdue_count"] for row in rows),
            "experiments": [dict(row) for row in rows]}
