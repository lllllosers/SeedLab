import argparse
import getpass
import re
import sqlite3

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.auth import hash_password, password_error
from app.db.session import SessionLocal
from app.models import User
from app.services import dev_reset
from app.services.common import record


def main() -> None:
    parser = argparse.ArgumentParser(description="SeedLab 管理命令")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin", help="创建管理员账户")
    create.add_argument("username")
    create.add_argument("--name", default="管理员")
    reset = commands.add_parser("reset-dev-data", help="仅开发环境：备份后重置业务数据，保留账号与登录会话")
    reset.add_argument("--dry-run", action="store_true", help="只查看删除范围和数量")
    reset.add_argument("--yes", action="store_true", help="明确确认删除全部开发业务数据")
    args = parser.parse_args()
    if args.command == "reset-dev-data":
        try:
            engine = SessionLocal.kw["bind"]
            counts = dev_reset.preview(engine)
            print("将删除：")
            for table, count in counts.items():
                if table not in dev_reset.PRESERVED:
                    print(f"  {dev_reset.LABELS.get(table, table)} {count}")
            print("将保留：")
            for table in ("users", "sessions"):
                print(f"  {dev_reset.LABELS[table]} {counts.get(table, 0)}")
            print("  数据库迁移版本、初始化码文件")
            if args.dry_run:
                print("[DONE] 仅预览，没有修改数据库。")
                return
            if not args.yes and input("输入 RESET 确认备份并删除全部开发业务数据：").strip() != "RESET":
                print("[SKIP] 已取消重置。")
                return
            result = dev_reset.reset(engine)
            print(f"[BACKUP] {result['backup']}")
            print("[DONE] 开发业务数据已重置，账号、登录会话和迁移版本均已保留。")
        except (RuntimeError, OSError, EOFError, sqlite3.Error, SQLAlchemyError) as exc:
            parser.exit(1, "重置未完成，业务删除已回滚或尚未开始。请检查备份目录权限与数据库状态。\n" if isinstance(exc, (sqlite3.Error, SQLAlchemyError)) else f"{exc}\n")
        return
    if args.command == "create-admin":
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,80}", args.username):
            parser.error("用户名须为 3 至 80 位字母、数字、下划线、点或连字符")
        password = getpass.getpass("密码（8 至 128 位）: ")
        if message := password_error(password):
            parser.error(message)
        if password != getpass.getpass("再次输入密码: "):
            parser.error("两次输入的密码不一致")
        with SessionLocal() as db:
            if db.scalar(select(User).where(User.username == args.username)):
                parser.error("用户名已存在")
            user = User(username=args.username, display_name=args.name,
                        password_hash=hash_password(password), is_admin=True,
                        must_change_password=False)
            db.add(user)
            db.flush()
            record(db, user.id, "create", "User", user.id, None,
                   {"username": user.username, "display_name": user.display_name, "is_admin": True})
            db.commit()
        print(f"管理员 {args.username} 已创建")


if __name__ == "__main__":
    main()
