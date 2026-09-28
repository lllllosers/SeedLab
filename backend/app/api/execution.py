from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (BatchObservationInput, ObservationInput, ObservationPatch,
                             StartExperimentInput)
from app.core.auth import current_user
from app.db.session import get_db
from app.models import ExperimentMaterial, GerminationDish, SeedlingSample, User
from app.services import germination_execution as execution


router = APIRouter(prefix="/experiments", tags=["germination execution"])


@router.post("/{experiment_id}/start")
def start_experiment(experiment_id: str, data: StartExperimentInput,
                     db: Session = Depends(get_db), user: User = Depends(current_user)):
    return execution.start_experiment(db, experiment_id, data.sown_at, user.id)


@router.get("/{experiment_id}/execution")
def get_execution(experiment_id: str, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return execution.execution_summary(db, experiment_id)


@router.post("/{experiment_id}/observations/batch")
def batch_observations(experiment_id: str, data: BatchObservationInput,
                       db: Session = Depends(get_db), user: User = Depends(current_user)):
    return execution.batch_create_observations(db, experiment_id, data, user.id)


@router.post("/{experiment_id}/observations", status_code=201)
def create_observation(experiment_id: str, data: ObservationInput,
                       db: Session = Depends(get_db), user: User = Depends(current_user)):
    batch = BatchObservationInput(observed_at=data.observed_at, entries=[data])
    return execution.batch_create_observations(db, experiment_id, batch, user.id)


@router.patch("/{experiment_id}/observations/{observation_id}")
def correct_observation(experiment_id: str, observation_id: str, data: ObservationPatch,
                        db: Session = Depends(get_db), user: User = Depends(current_user)):
    return execution.correct_observation(db, experiment_id, observation_id, data, user.id)


@router.delete("/{experiment_id}/observations/{observation_id}", status_code=204)
def delete_observation(experiment_id: str, observation_id: str,
                       db: Session = Depends(get_db), user: User = Depends(current_user)):
    execution.delete_observation(db, experiment_id, observation_id, user.id)


@router.get("/{experiment_id}/samples")
def list_samples(experiment_id: str, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    execution.execution_summary(db, experiment_id)
    rows = db.execute(select(SeedlingSample, GerminationDish).join(
        GerminationDish, SeedlingSample.dish_id == GerminationDish.id).join(
        ExperimentMaterial, GerminationDish.material_id == ExperimentMaterial.id).where(
        ExperimentMaterial.experiment_id == experiment_id).order_by(
        GerminationDish.code, SeedlingSample.sample_number))
    return [{"id": sample.id, "dish_id": dish.id, "dish_code": dish.code,
             "sample_number": sample.sample_number,
             "germinated_at": execution.iso_utc(sample.germinated_at),
             "source_observation_id": sample.source_observation_id,
             "position_label": sample.position_label}
            for sample, dish in rows]
