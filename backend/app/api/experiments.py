from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.schemas import ExperimentIn, ExperimentOut, ExperimentPatch, TerminateExperiment
from app.core.auth import current_user
from app.db.session import get_db
from app.models import Experiment, User
from app.models.entities import now_utc
from app.services.common import commit_or_conflict, flush_or_conflict, next_code, record, require_entity
from app.services.experiment_config import editable, set_status
from app.services import experiment_lifecycle as lifecycle


router = APIRouter(prefix="/experiments", tags=["experiments"])


def snapshot(item: Experiment) -> dict:
    return ExperimentOut.model_validate(item).model_dump(mode="json")


@router.get("", response_model=list[ExperimentOut])
def list_experiments(q: str = "", status: str | None = None, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    statement = select(Experiment)
    if q.strip():
        statement = statement.where(or_(Experiment.code.ilike(f"%{q.strip()}%"), Experiment.name.ilike(f"%{q.strip()}%")))
    if status:
        statement = statement.where(Experiment.status == status)
    return db.scalars(statement.order_by(Experiment.created_at.desc()).limit(500)).all()


@router.post("", response_model=ExperimentOut, status_code=201)
def create_experiment(data: ExperimentIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = Experiment(code=next_code(db, Experiment, f"EXP-{datetime.now().year}-", 3), owner_id=user.id, **data.model_dump())
    db.add(item)
    flush_or_conflict(db)
    record(db, user.id, "create", "Experiment", item.id, None, snapshot(item))
    commit_or_conflict(db)
    return item


@router.get("/{item_id}", response_model=ExperimentOut)
def get_experiment(item_id: str, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return require_entity(db, Experiment, item_id)


@router.patch("/{item_id}", response_model=ExperimentOut)
def update_experiment(item_id: str, data: ExperimentPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = require_entity(db, Experiment, item_id)
    if item.status in {"completed", "cancelled"}:
        raise HTTPException(409, "已结束的实验信息只供查阅；已完成实验的测定纠错请进入测定记录")
    before = snapshot(item)
    patch = data.model_dump(exclude_unset=True)
    for key, value in patch.items():
        if key in {"name", "status"} and value is None:
            raise HTTPException(422, "实验名称和当前状态不能为空")
        if key == "planned_start_date":
            editable(item)
        if key != "status":
            setattr(item, key, value)
    if "status" in patch:
        set_status(db, item, patch["status"])
        if item.status in {"completed", "cancelled"} and item.ended_at is None:
            item.ended_at = now_utc()
    flush_or_conflict(db)
    after = snapshot(item)
    if before != after:
        record(db, user.id, "update", "Experiment", item.id, before, after)
    commit_or_conflict(db)
    return item


@router.delete("/{item_id}", status_code=204)
def delete_experiment(item_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    lifecycle.delete_unused(db, item_id, user.id)


@router.get("/{item_id}/completion-check")
def completion_check(item_id: str, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return lifecycle.completion_check(db, item_id)


@router.post("/{item_id}/complete", response_model=ExperimentOut)
def complete(item_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return lifecycle.complete(db, item_id, user.id)


@router.post("/{item_id}/terminate", response_model=ExperimentOut)
def terminate(item_id: str, data: TerminateExperiment, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return lifecycle.terminate(db, item_id, data.reason, user.id)
