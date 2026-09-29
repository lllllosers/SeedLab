from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import MeasurementInput, MeasurementPatch, PositionLabelPatch
from app.core.auth import current_user
from app.db.session import get_db
from app.models import User
from app.services import seedling_measurement as service


router = APIRouter(prefix="/experiments", tags=["seedling measurement"])


@router.get("/{experiment_id}/measurement-tasks")
def tasks(experiment_id: str, status: str | None = None, dag: int | None = None,
          q: str | None = None, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return service.task_data(db, experiment_id, status, dag, q)


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
