"""Public status and token-protected first administrator creation."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.schemas import BootstrapInput, UserOut
from app.core.auth import COOKIE_NAME, create_session, hash_password, require_password
from app.core.bootstrap import read_token, retire_token
from app.core.config import get_settings
from app.db.session import get_db
from app.models import User
from app.services.common import record


router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/status")
def status(db: Session = Depends(get_db)):
    return {"initialized": db.scalar(select(User.id).limit(1)) is not None}


@router.post("/bootstrap", status_code=201)
def bootstrap(data: BootstrapInput, response: Response, db: Session = Depends(get_db)):
    require_password(data.password)
    if data.password != data.confirm_password:
        raise HTTPException(422, "两次输入的密码不一致")
    try:
        # A SQLite write reservation serializes competing first-user requests.
        db.execute(text("BEGIN IMMEDIATE"))
        if db.scalar(select(User.id).limit(1)) is not None:
            raise HTTPException(409, "系统已经初始化，不能再次创建首个管理员")
        stored = read_token()
        if stored is None or not secrets.compare_digest(stored, data.bootstrap_token):
            raise HTTPException(403, "初始化码无效")
        user = User(username=data.username, display_name=data.display_name,
                    password_hash=hash_password(data.password), is_admin=True,
                    must_change_password=False)
        db.add(user)
        db.flush()
        record(db, user.id, "create", "User", user.id, None,
               {"username": user.username, "display_name": user.display_name,
                "is_admin": True, "is_active": True, "bootstrap": True})
        raw, csrf = create_session(db, user, commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    retire_token()
    response.set_cookie(COOKIE_NAME, raw, httponly=True, secure=get_settings().seedlab_cookie_secure,
                        samesite="lax", max_age=get_settings().seedlab_session_hours * 3600, path="/")
    return {"user": UserOut.model_validate(user), "csrf_token": csrf}
