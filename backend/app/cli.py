import argparse
import getpass
import re

from sqlalchemy import select

from app.core.auth import hash_password, password_error
from app.db.session import SessionLocal
from app.models import User


def main() -> None:
    parser = argparse.ArgumentParser(description="SeedLab 管理命令")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin", help="创建管理员账户")
    create.add_argument("username")
    create.add_argument("--name", default="管理员")
    args = parser.parse_args()
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
            db.add(User(username=args.username, display_name=args.name,
                        password_hash=hash_password(password), is_admin=True,
                        must_change_password=False))
            db.commit()
        print(f"管理员 {args.username} 已创建")


if __name__ == "__main__":
    main()
