from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.schemas import AuditOut, PasswordReset, UserCreate, UserOut, UserPatch
from app.core.auth import admin_user, current_user, hash_password, require_password
from app.db.session import get_db
from app.models import AuditLog, Experiment, SeedLot, SessionToken, Taxon, User
from app.services.common import commit_or_conflict, flush_or_conflict, record, require_entity
from app.services.measurement_query import dashboard as measurement_dashboard
from app.services.audit_history import list_history


router = APIRouter(tags=["system"])


def safe_user_state(user: User) -> dict:
    return {"username": user.username, "display_name": user.display_name,
            "is_admin": user.is_admin, "is_active": user.is_active}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _user: User = Depends(current_user)):
    count = lambda model: db.scalar(select(func.count()).select_from(model)) or 0
    return {
        "taxa": count(Taxon), "seed_lots": count(SeedLot), "experiments": count(Experiment),
        "active_experiments": db.scalar(select(func.count()).select_from(Experiment).where(Experiment.status == "active")) or 0,
        "active_experiment_ids": list(db.scalars(select(Experiment.id).where(Experiment.status == "active").order_by(Experiment.created_at.desc()))),
        "recent_experiments": [{"id": x.id, "code": x.code, "name": x.name, "status": x.status} for x in db.scalars(select(Experiment).order_by(Experiment.created_at.desc()).limit(5))],
        "recent_actions": [{"id": x.id, "action": x.action, "entity_type": x.entity_type, "created_at": x.created_at.isoformat()} for x in db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(5))],
        "measurement": measurement_dashboard(db),
    }


@router.get("/audit-logs")
def audit_logs(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
               action: str | None = None, entity_type: str | None = None, q: str | None = None,
               db: Session = Depends(get_db), _user: User = Depends(current_user)):
    return list_history(db, page, page_size, action, entity_type, q)


@router.get("/users", response_model=list[UserOut])
def users(db: Session = Depends(get_db), _admin: User = Depends(admin_user)):
    return db.scalars(select(User).order_by(User.created_at)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(data: UserCreate, db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    require_password(data.password)
    user = User(username=data.username, display_name=data.display_name.strip(),
                password_hash=hash_password(data.password), is_admin=data.is_admin,
                must_change_password=True)
    if not user.display_name:
        raise HTTPException(422, "请填写显示姓名")
    db.add(user)
    flush_or_conflict(db)
    record(db, admin.id, "create", "User", user.id, None, safe_user_state(user))
    commit_or_conflict(db)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, data: UserPatch, db: Session = Depends(get_db),
                admin: User = Depends(admin_user)):
    target = require_entity(db, User, user_id)
    patch = data.model_dump(exclude_unset=True)
    if any(value is None for value in patch.values()):
        raise HTTPException(422, "用户姓名、角色和状态不能为空")
    if "display_name" in patch:
        patch["display_name"] = patch["display_name"].strip()
        if not patch["display_name"]:
            raise HTTPException(422, "请填写显示姓名")
    if target.id == admin.id and patch.get("is_active") is False:
        raise HTTPException(409, "不能停用自己的账号")
    if target.id == admin.id and patch.get("is_admin") is False:
        raise HTTPException(409, "不能取消自己的管理员权限")
    losing_admin = target.is_admin and target.is_active and (
        patch.get("is_admin", target.is_admin) is False or
        patch.get("is_active", target.is_active) is False)
    if losing_admin and (db.scalar(select(func.count()).select_from(User).where(
            User.is_admin.is_(True), User.is_active.is_(True))) or 0) <= 1:
        raise HTTPException(409, "不能移除最后一个启用的管理员")
    before = safe_user_state(target)
    for key, value in patch.items():
        setattr(target, key, value)
    invalidated_sessions = patch.get("is_active") is False
    if invalidated_sessions:
        db.execute(delete(SessionToken).where(SessionToken.user_id == target.id))
    after = safe_user_state(target)
    if after != before:
        record(db, admin.id, "update", "User", target.id, before, after)
    if after != before or invalidated_sessions:
        commit_or_conflict(db)
    return target


@router.post("/users/{user_id}/reset-password", response_model=UserOut)
def reset_user_password(user_id: str, data: PasswordReset,
                        db: Session = Depends(get_db), admin: User = Depends(admin_user)):
    target = require_entity(db, User, user_id)
    if target.id == admin.id:
        raise HTTPException(409, "请通过个人改密入口修改自己的密码")
    require_password(data.password)
    before = {"initial_change_required": target.must_change_password}
    target.password_hash = hash_password(data.password)
    target.must_change_password = True
    db.execute(delete(SessionToken).where(SessionToken.user_id == target.id))
    record(db, admin.id, "update", "User", target.id, before,
           {"initial_change_required": True, "credential_event": "admin_reset"})
    commit_or_conflict(db)
    return target
