from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import Login, UserOut
from app.core.auth import COOKIE_NAME, check_password, create_session, current_user, session_for_request
from app.core.config import get_settings
from app.db.session import get_db
from app.models import User


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(data: Login, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == data.username))
    if user is None or not user.is_active or not check_password(user.password_hash, data.password):
        raise HTTPException(401, "用户名或密码错误")
    raw, csrf = create_session(db, user)
    response.set_cookie(COOKIE_NAME, raw, httponly=True, secure=get_settings().seedlab_cookie_secure,
                        samesite="lax", max_age=get_settings().seedlab_session_hours * 3600, path="/")
    return {"user": UserOut.model_validate(user), "csrf_token": csrf}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    session = session_for_request(request, db)
    return {"user": UserOut.model_validate(session.user), "csrf_token": session.csrf_token}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    session = session_for_request(request, db)
    db.delete(session)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
