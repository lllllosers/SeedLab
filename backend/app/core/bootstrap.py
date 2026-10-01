"""One-time local bootstrap secret. Never expose it through an API response."""

import os
import secrets
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import User


def token_path(settings: Settings | None = None) -> Path:
    return Path((settings or get_settings()).seedlab_bootstrap_token_path)


def read_token(settings: Settings | None = None) -> str | None:
    path = token_path(settings)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def retire_token(settings: Settings | None = None) -> None:
    token_path(settings).unlink(missing_ok=True)


def ensure_bootstrap_token(db: Session, settings: Settings | None = None, *, announce=True) -> None:
    if db.scalar(select(User.id).limit(1)) is not None:
        retire_token(settings)
        return
    path = token_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        token = read_token(settings)
        if token is None:
            raise RuntimeError("初始化码文件为空，请在服务器本机检查并重启")
    else:
        token = secrets.token_urlsafe(32)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(token + "\n")
    if announce:
        print("SeedLab 尚未初始化。请访问 /setup，并使用本机终端显示的一次性初始化码。", flush=True)
        print(f"SeedLab Bootstrap Token: {token}", flush=True)
