from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.contracts.experiments import ExperimentIn, ExperimentOut, ExperimentPatch, TerminateExperiment
from app.core.auth import current_user
from app.db.session import get_db
from app.models import Experiment, User
from app.core.experiment_types import ExperimentTypeRegistry
from app.api.experiment_dependencies import get_experiment_registry
from app.services.common import commit_or_conflict, flush_or_conflict, record, require_entity
from app.services.experiment_identity import next_experiment_code, experiment_batch_month
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
    item = Experiment(code=next_experiment_code(db, data.experiment_type, experiment_batch_month(data.planned_start_date)),
                      owner_id=user.id, **data.model_dump())
    db.add(item)
    flush_or_conflict(db)
    record(db, user.id, "create", "Experiment", item.id, None, snapshot(item))
    commit_or_conflict(db)
    return item


@router.get("/{item_id}", response_model=ExperimentOut)
def get_experiment(item_id: str, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return require_entity(db, Experiment, item_id)


@router.patch("/{item_id}", response_model=ExperimentOut)
def update_experiment(item_id: str, data: ExperimentPatch, db: Session = Depends(get_db), user: User = Depends(current_user),
                      registry: ExperimentTypeRegistry = Depends(get_experiment_registry)):
    return lifecycle.update(db, item_id, data, user.id, registry)


@router.delete("/{item_id}", status_code=204)
def delete_experiment(item_id: str, db: Session = Depends(get_db), user: User = Depends(current_user),
                     registry: ExperimentTypeRegistry = Depends(get_experiment_registry)):
    lifecycle.delete_unused(db, item_id, user.id, registry)


@router.get("/{item_id}/completion-check")
def completion_check(item_id: str, db: Session = Depends(get_db), _user: User = Depends(current_user),
                     registry: ExperimentTypeRegistry = Depends(get_experiment_registry)):
    return lifecycle.completion_check(db, item_id, registry)


@router.post("/{item_id}/complete", response_model=ExperimentOut)
def complete(item_id: str, db: Session = Depends(get_db), user: User = Depends(current_user),
                     registry: ExperimentTypeRegistry = Depends(get_experiment_registry)):
    return lifecycle.complete(db, item_id, user.id, registry)


@router.post("/{item_id}/terminate", response_model=ExperimentOut)
def terminate(item_id: str, data: TerminateExperiment, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return lifecycle.terminate(db, item_id, data.reason, user.id)
