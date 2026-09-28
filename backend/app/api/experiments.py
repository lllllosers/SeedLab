from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.schemas import ExperimentIn, ExperimentOut, ExperimentPatch
from app.core.auth import current_user
from app.db.session import get_db
from app.models import Experiment, User
from app.models.entities import now_utc
from app.services.common import commit_or_conflict, flush_or_conflict, next_code, record, require_entity


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
    item = Experiment(code=next_code(db, Experiment, f"EXP-{datetime.now().year}-", 3), **data.model_dump())
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
    before = snapshot(item)
    patch = data.model_dump(exclude_unset=True)
    for key, value in patch.items():
        if key in {"name", "status"} and value is None:
            raise HTTPException(422, f"{key} 不可为空")
        setattr(item, key, value)
    if "status" in patch:
        if item.status == "active" and item.started_at is None:
            item.started_at = now_utc()
        if item.status in {"completed", "cancelled"} and item.ended_at is None:
            item.ended_at = now_utc()
    flush_or_conflict(db)
    record(db, user.id, "update", "Experiment", item.id, before, snapshot(item))
    commit_or_conflict(db)
    return item


@router.delete("/{item_id}", status_code=204)
def delete_experiment(item_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = require_entity(db, Experiment, item_id)
    before = snapshot(item)
    db.delete(item)
    record(db, user.id, "delete", "Experiment", item_id, before, None)
    commit_or_conflict(db)
