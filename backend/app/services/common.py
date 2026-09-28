from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog


def next_code(db: Session, model: type, prefix: str, width: int = 4) -> str:
    codes = db.scalars(select(model.code).where(model.code.like(f"{prefix}%"))).all()
    highest = max((int(code[len(prefix):]) for code in codes if code[len(prefix):].isdigit()), default=0)
    return f"{prefix}{highest + 1:0{width}d}"


def record(db: Session, user_id: str, action: str, entity_type: str, entity_id: str, before: dict | None, after: dict | None) -> None:
    db.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id, before=before, after=after))


def commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "编号或名称已存在，或数据正在被引用") from exc


def flush_or_conflict(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "编号或名称已存在，或数据正在被引用") from exc


def require_entity(db: Session, model: type, entity_id: str):
    item = db.get(model, entity_id)
    if item is None:
        raise HTTPException(404, "记录不存在")
    return item
