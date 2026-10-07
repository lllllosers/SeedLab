"""Compatibility helpers for non-growth callers; growth uses application_support."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.errors import ConflictError, NotFoundError
from app.services import application_support
from app.services.application_support import record


def next_code(db: Session, model: type, prefix: str, width: int = 4) -> str:
    codes = db.scalars(select(model.code).where(model.code.like(f"{prefix}%"))).all()
    highest = max((int(code[len(prefix):]) for code in codes if code[len(prefix):].isdigit()), default=0)
    return f"{prefix}{highest + 1:0{width}d}"


def commit_or_conflict(db: Session) -> None:
    try:
        application_support.commit_or_conflict(db)
    except ConflictError as exc:
        raise HTTPException(409, exc.detail) from exc.__cause__


def flush_or_conflict(db: Session) -> None:
    try:
        application_support.flush_or_conflict(db)
    except ConflictError as exc:
        raise HTTPException(409, exc.detail) from exc.__cause__


def require_entity(db: Session, model: type, entity_id: str):
    try:
        return application_support.require_entity(db, model, entity_id)
    except NotFoundError as exc:
        raise HTTPException(404, exc.detail) from exc.__cause__
