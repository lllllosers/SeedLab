import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import AuditOut, UserCreate, UserOut
from app.core.auth import admin_user, current_user, hash_password
from app.db.session import get_db
from app.models import AuditLog, Experiment, ImportJob, SeedLot, Taxon, User
from app.services.common import commit_or_conflict, flush_or_conflict, next_code, record


router = APIRouter(tags=["system"])


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _user: User = Depends(current_user)):
    count = lambda model: db.scalar(select(func.count()).select_from(model)) or 0
    return {
        "taxa": count(Taxon), "seed_lots": count(SeedLot), "experiments": count(Experiment),
        "active_experiments": db.scalar(select(func.count()).select_from(Experiment).where(Experiment.status == "active")) or 0,
        "recent_experiments": [{"id": x.id, "code": x.code, "name": x.name, "status": x.status} for x in db.scalars(select(Experiment).order_by(Experiment.created_at.desc()).limit(5))],
        "recent_actions": [{"id": x.id, "action": x.action, "entity_type": x.entity_type, "created_at": x.created_at.isoformat()} for x in db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(5))],
    }


@router.get("/audit-logs", response_model=list[AuditOut])
def audit_logs(db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100)).all()


@router.get("/users", response_model=list[UserOut])
def users(db: Session = Depends(get_db), _admin: User = Depends(admin_user)):
    return db.scalars(select(User).order_by(User.created_at)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    user = User(username=data.username, display_name=data.display_name, password_hash=hash_password(data.password), is_admin=data.is_admin)
    db.add(user)
    flush_or_conflict(db)
    record(db, admin.id, "create", "User", user.id, None, UserOut.model_validate(user).model_dump())
    commit_or_conflict(db)
    return user


@router.get("/export/taxa.csv")
def export_taxa(db: Session = Depends(get_db), _user: User = Depends(current_user)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["code", "scientific_name", "common_name", "family", "is_active", "notes"])
    for item in db.scalars(select(Taxon).order_by(Taxon.code)):
        writer.writerow([item.code, item.scientific_name, item.common_name or "", item.family or "", item.is_active, item.notes or ""])
    return StreamingResponse(iter(["\ufeff" + output.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="seedlab-taxa.csv"'})


@router.post("/import/taxa", status_code=201)
async def import_taxa(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    filename = file.filename or ""
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(422, "请上传 .xlsx 文件")
    content = await file.read(2_000_001)
    if len(content) > 2_000_000:
        raise HTTPException(413, "文件不能超过 2 MB")
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        header = [str(value or "").strip() for value in next(rows)]
        if "scientific_name" not in header:
            raise ValueError("首行必须包含 scientific_name 列")
        entries = []
        for line, values in enumerate(rows, start=2):
            row = dict(zip(header, values))
            name = str(row.get("scientific_name") or "").strip()
            if not name:
                if any(value is not None for value in values):
                    raise ValueError(f"第 {line} 行缺少 scientific_name")
                continue
            entries.append({"scientific_name": name, "common_name": str(row.get("common_name") or "").strip() or None,
                            "family": str(row.get("family") or "").strip() or None})
        workbook.close()
    except (ValueError, StopIteration, OSError) as exc:
        raise HTTPException(422, f"文件格式错误：{exc}") from exc
    if len(entries) > 500:
        raise HTTPException(422, "一次最多导入 500 行")
    names = [entry["scientific_name"] for entry in entries]
    if len(set(names)) != len(names) or db.scalar(select(Taxon.id).where(Taxon.scientific_name.in_(names)).limit(1)):
        raise HTTPException(409, "学名在文件或数据库中重复")
    job = ImportJob(user_id=user.id, filename=filename, status="completed", total_rows=len(entries), successful_rows=len(entries))
    db.add(job)
    start = int(next_code(db, Taxon, "SP-").removeprefix("SP-"))
    for offset, entry in enumerate(entries):
        item = Taxon(code=f"SP-{start + offset:04d}", **entry)
        db.add(item)
        flush_or_conflict(db)
        record(db, user.id, "import", "Taxon", item.id, None, {"code": item.code, **entry})
    commit_or_conflict(db)
    return {"id": job.id, "imported": len(entries)}
