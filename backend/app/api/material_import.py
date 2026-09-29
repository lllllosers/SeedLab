import io
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session

from app.core.auth import current_user
from app.db.session import get_db
from app.models import User
from app.services import material_import


router = APIRouter(tags=["integrated material import"])


@router.get("/export/materials-template.xlsx")
def template(_user: User = Depends(current_user)):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "种子材料一体导入"
    sheet.append(material_import.COLUMNS)
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 22
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    output.seek(0)
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="seedlab-materials-template.xlsx"'})


async def _content(file: UploadFile) -> bytes:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(422, "请选择 .xlsx 格式的种子材料文件")
    content = await file.read(8_000_001)
    if len(content) > 8_000_000:
        raise HTTPException(413, "文件不能超过 8 MB")
    return content


@router.post("/import/materials/preview")
async def preview(file: UploadFile = File(...), db: Session = Depends(get_db),
                  _user: User = Depends(current_user)):
    return material_import.preview(db, await _content(file))


@router.post("/import/materials/confirm")
async def confirm(file: UploadFile = File(...), decisions: str = Form("{}"),
                  db: Session = Depends(get_db), user: User = Depends(current_user)):
    try:
        parsed = json.loads(decisions)
        if not isinstance(parsed, dict):
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "材料确认选项无效，请重新预检") from exc
    return material_import.confirm(db, await _content(file), file.filename or "materials.xlsx", parsed, user.id)
