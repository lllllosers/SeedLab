import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models import SessionToken, User
from app.models.entities import now_utc


hasher = PasswordHasher()
COOKIE_NAME = "seedlab_session"
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def password_error(password: str) -> str | None:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        return "密码长度须为 8 至 128 位"
    return None


def require_password(password: str) -> None:
    if message := password_error(password):
        raise HTTPException(422, message)


def hash_password(password: str) -> str:
    return hasher.hash(password)


def check_password(hash_value: str, password: str) -> bool:
    try:
        return hasher.verify(hash_value, password)
    except VerifyMismatchError:
        return False


def create_session(db: Session, user: User, *, commit: bool = True) -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    db.add(SessionToken(user_id=user.id, token_hash=hashlib.sha256(raw.encode()).hexdigest(), csrf_token=csrf,
                        expires_at=now_utc() + timedelta(hours=get_settings().seedlab_session_hours)))
    if commit:
        db.commit()
    else:
        db.flush()
    return raw, csrf


def session_for_request(request: Request, db: Session) -> SessionToken:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        raise HTTPException(401, "请先登录")
    session = db.scalar(select(SessionToken).where(SessionToken.token_hash == hashlib.sha256(raw.encode()).hexdigest()))
    if session is None or session.expires_at.replace(tzinfo=None) <= now_utc().replace(tzinfo=None) or not session.user.is_active:
        raise HTTPException(401, "登录已失效")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not secrets.compare_digest(supplied, session.csrf_token):
            raise HTTPException(403, "CSRF 校验失败")
    return session


def authenticated_user(request: Request, db: Session = Depends(get_db)) -> User:
    return session_for_request(request, db).user


def current_user(user: User = Depends(authenticated_user)) -> User:
    if user.must_change_password:
        raise HTTPException(403, "请先修改初始密码")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return user
