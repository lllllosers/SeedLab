"""Shared persistence and audit helpers without transport dependencies."""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.contracts.errors import ConflictError, NotFoundError
from app.models import AuditLog


def record(db: Session, user_id: str, action: str, entity_type: str, entity_id: str, before: dict | None, after: dict | None) -> None:
    db.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id, before=before, after=after))


def commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("编号或名称已存在，或数据正在被引用") from exc


def flush_or_conflict(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("编号或名称已存在，或数据正在被引用") from exc


def require_entity(db: Session, model: type, entity_id: str):
    item = db.get(model, entity_id)
    if item is None:
        raise NotFoundError("找不到所选内容，请刷新页面后重试")
    return item
