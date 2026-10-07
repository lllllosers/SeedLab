import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.contracts.germination import (BatchObservationInput, ObservationInput, ObservationPatch,
                             SowDishesInput, CorrectSowingInput, CancelDishInput)
from app.core.auth import current_user
from app.db.session import get_db
from app.models import Experiment, ExperimentMaterial, GerminationDish, SeedlingSample, User
from app.services import germination_execution as execution
from app.services import sowing_workflow as sowing
from app.services import germination_config as design
from app.services.common import require_entity
from app.services.ordering import display_number, dish_display_number, field_number, sample_display_number


router = APIRouter(prefix="/experiments", tags=["germination execution"])


@router.get("/{experiment_id}/sowing-sheet.xlsx")
def sowing_sheet(experiment_id: str, db: Session = Depends(get_db), _user: User = Depends(current_user)):
    experiment = require_entity(db, Experiment, experiment_id)
    if not experiment.numbering_locked_at:
        raise HTTPException(422, "请先确认置床编号，再下载正式清单")
    config = design.configuration(db, experiment_id)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "置床清单"
    sheet.append(("实验内材料编号", "中文名", "学名", "原始材料编号", "系统种子批次编号", "来源",
                  "采集/获得日期", "重复数", "每皿种子数", "培养皿现场编号"))
    for material in config["materials"]:
        number = display_number(material["experiment_number"])
        count = material["effective_replicate_count"]
        for replicate in range(1, count + 1):
            sheet.append((number, material["taxon_common_name"], material["taxon_scientific_name"],
                          material["source_code"], material["seed_lot_code"], material["source"],
                          material["collected_at"], count, material["effective_seeds_per_dish"],
                          dish_display_number(material["experiment_number"], replicate, count)))
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    output.seek(0)
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="seedlab-sowing-sheet.xlsx"'})


@router.post("/{experiment_id}/confirm-numbers")
def confirm_numbers(experiment_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return sowing.confirm_numbers(db, experiment_id, user.id)


@router.post("/{experiment_id}/reopen-design")
def reopen_design(experiment_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return sowing.unlock_numbers(db, experiment_id, user.id)


@router.post("/{experiment_id}/sowing/batch")
def batch_sowing(experiment_id: str, data: SowDishesInput,
                 db: Session = Depends(get_db), user: User = Depends(current_user)):
    return sowing.sow_dishes(db, experiment_id, data.dish_ids, data.sown_at, user.id)


@router.patch("/{experiment_id}/sowing/{dish_id}")
def correct_sowing(experiment_id: str, dish_id: str, data: CorrectSowingInput,
                   db: Session = Depends(get_db), user: User = Depends(current_user)):
    return sowing.correct_sowing(db, experiment_id, dish_id, data.sown_at, user.id)


@router.post("/{experiment_id}/sowing/{dish_id}/cancel")
def cancel_dish(experiment_id: str, dish_id: str, data: CancelDishInput,
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    return sowing.cancel_dish(db, experiment_id, dish_id, data.reason, user.id)


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
    rows = db.execute(select(SeedlingSample, GerminationDish, ExperimentMaterial).join(
        GerminationDish, SeedlingSample.dish_id == GerminationDish.id).join(
        ExperimentMaterial, GerminationDish.material_id == ExperimentMaterial.id).where(
        ExperimentMaterial.experiment_id == experiment_id).order_by(
        ExperimentMaterial.experiment_number, GerminationDish.replicate_no, SeedlingSample.sample_number)).all()
    counts = dict(db.execute(select(GerminationDish.material_id, func.max(GerminationDish.replicate_no))
                            .join(ExperimentMaterial).where(ExperimentMaterial.experiment_id == experiment_id)
                            .group_by(GerminationDish.material_id)).all())
    return [{"id": sample.id, "dish_id": dish.id, "dish_code": dish.code,
             "sample_number": sample.sample_number,
             "field_number": field_number(material, counts[material.id], dish.replicate_no),
             "sample_display_number": sample_display_number(material.experiment_number, dish.replicate_no,
                                                            counts[material.id], sample.sample_number),
             "germinated_at": execution.iso_utc(sample.germinated_at),
             "source_observation_id": sample.source_observation_id,
             "position_label": sample.position_label}
            for sample, dish, material in rows]
