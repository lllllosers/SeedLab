from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import current_user
from app.db.session import get_db
from app.models import User
from app.services.workbook_export import build
from app.services.catalog_export import build as build_catalog


router = APIRouter(tags=["experiment workbooks"])


class WorkbookRequest(BaseModel):
    experiment_ids: list[str] = Field(min_length=1)


@router.post("/export/experiments/workbook.xlsx")
def export_workbook(data: WorkbookRequest, db: Session = Depends(get_db),
                    _user: User = Depends(current_user)):
    output = build(db, data.experiment_ids)
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="seedlab-experiments.xlsx"'})


@router.get("/export/catalog.xlsx")
def export_catalog(db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return StreamingResponse(build_catalog(db), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="seedlab-catalog.xlsx"'})
