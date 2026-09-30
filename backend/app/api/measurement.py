from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas import MeasurementInput, MeasurementPatch, PositionLabelPatch
from app.core.auth import current_user
from app.db.session import get_db
from app.models import User
from app.services import seedling_measurement as service
from app.services import measurement_query


router = APIRouter(prefix="/experiments", tags=["seedling measurement"])


@router.get("/{experiment_id}/measurement-tasks")
def tasks(experiment_id: str, status: str | None = None, dag: int | None = None,
          q: str | None = None, material_id: str | None = None, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return service.task_data(db, experiment_id, status, dag, q, material_id)


@router.get("/{experiment_id}/measurement-worklist")
def worklist(experiment_id: str, status: str = "pending", dag: int | None = None, q: str | None = None,
             page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
             db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return measurement_query.worklist(db, experiment_id, status, dag, q, page, page_size)


@router.get("/{experiment_id}/measurement-records")
def records(experiment_id: str, q: str | None = None, material_ids: list[str] = Query(default=[]),
            dag: int | None = None, date_from: date | None = None, date_to: date | None = None,
            page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
            db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return measurement_query.records(db, experiment_id, q, material_ids, dag, date_from, date_to, page, page_size)


@router.get("/{experiment_id}/measurement-history/{material_id}")
def history(experiment_id: str, material_id: str, db: Session = Depends(get_db),
            _user: User = Depends(current_user)):
    return service.history(db, experiment_id, material_id)


@router.post("/{experiment_id}/measurements", status_code=201)
def create(experiment_id: str, data: MeasurementInput, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    return service.create(db, experiment_id, data, user.id)


@router.patch("/{experiment_id}/measurements/{measurement_id}")
def update(experiment_id: str, measurement_id: str, data: MeasurementPatch,
           db: Session = Depends(get_db), user: User = Depends(current_user)):
    return service.update(db, experiment_id, measurement_id, data, user.id)


@router.delete("/{experiment_id}/measurements/{measurement_id}", status_code=204)
def delete(experiment_id: str, measurement_id: str, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    service.delete(db, experiment_id, measurement_id, user.id)


@router.patch("/{experiment_id}/samples/{sample_id}/position")
def update_position(experiment_id: str, sample_id: str, data: PositionLabelPatch,
                    db: Session = Depends(get_db), user: User = Depends(current_user)):
    return service.update_position(db, experiment_id, sample_id, data.position_label, user.id)
