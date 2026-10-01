from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.schemas import ChangePassword, Login, UserOut
from app.core.auth import COOKIE_NAME, authenticated_user, check_password, create_session, hash_password, require_password, session_for_request
from app.db.session import get_db
from app.models import SessionToken, User
from app.services.common import record


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(data: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    settings = request.app.state.settings
    user = db.scalar(select(User).where(User.username == data.username))
    if user is None or not user.is_active or not check_password(user.password_hash, data.password):
        raise HTTPException(401, "用户名或密码错误")
    raw, csrf = create_session(db, user, settings=settings)
    response.set_cookie(COOKIE_NAME, raw, httponly=True, secure=settings.seedlab_cookie_secure,
                        samesite="lax", max_age=settings.seedlab_session_hours * 3600, path="/")
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


@router.post("/change-password", status_code=204)
def change_password(data: ChangePassword, response: Response,
                    db: Session = Depends(get_db), user: User = Depends(authenticated_user)):
    if not check_password(user.password_hash, data.current_password):
        raise HTTPException(403, "当前密码错误")
    require_password(data.new_password)
    if data.new_password != data.confirm_password:
        raise HTTPException(422, "两次输入的新密码不一致")
    if data.new_password == data.current_password:
        raise HTTPException(422, "新密码不能与当前密码相同")
    before = {"initial_change_required": user.must_change_password}
    user.password_hash = hash_password(data.new_password)
    user.must_change_password = False
    db.execute(delete(SessionToken).where(SessionToken.user_id == user.id))
    record(db, user.id, "update", "User", user.id, before,
           {"initial_change_required": False, "credential_event": "self_change"})
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
