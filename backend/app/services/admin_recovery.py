"""Local offline credential recovery for existing administrators only."""
from contextlib import closing
from pathlib import Path
import sqlite3

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.auth import hash_password, password_error
from app.db.session import make_engine
from app.models import User, SessionToken
from app.services.database_upgrade import database_lease, inspect_schema, read_revision, migration_graph, validate_database
from app.services.database_recovery import require_no_writer


def schema_information(database, migrations):
    target, _ = migration_graph(migrations)
    current = read_revision(Path(database)) if Path(database).is_file() else None
    return {"current": current, "target": target}


def administrators(database):
    path = Path(database).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        return [{"id": row[0], "username": row[1], "display_name": row[2], "active": bool(row[3])}
                for row in connection.execute("SELECT id, username, display_name, is_active FROM users WHERE is_admin=1 ORDER BY username")]


def reset_administrator(database, migrations, user_id, password, confirmation):
    if password != confirmation:
        raise ValueError("两次输入的密码不一致，请重新输入。")
    if message := password_error(password):
        raise ValueError(message + "。")
    path = Path(database).absolute()
    url = "sqlite:///" + path.as_posix()
    with database_lease(url):
        plan = inspect_schema(url, migrations, allow_create=False)
        if plan.state != "current":
            raise ValueError("数据库与当前程序不匹配，请先完成程序升级后再恢复管理员登录。")
        require_no_writer(path)
        validate_database(path)
        engine = make_engine(url)
        try:
            with Session(engine) as session, session.begin():
                user = session.scalar(select(User).where(User.id == user_id, User.is_admin.is_(True)))
                if user is None:
                    raise ValueError("所选管理员已不存在，请刷新管理员列表。")
                if not user.is_active:
                    raise ValueError("该管理员已停用，请由其他管理员先恢复启用；密码尚未修改。")
                user.password_hash = hash_password(password)
                user.must_change_password = False
                session.execute(delete(SessionToken).where(SessionToken.user_id == user.id))
        finally:
            engine.dispose()
