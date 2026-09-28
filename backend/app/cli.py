import argparse
import getpass

from sqlalchemy import select

from app.core.auth import hash_password
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
        password = getpass.getpass("密码（至少 10 位）: ")
        if len(password) < 10 or password != getpass.getpass("再次输入密码: "):
            parser.error("密码不一致或少于 10 位")
        with SessionLocal() as db:
            if db.scalar(select(User).where(User.username == args.username)):
                parser.error("用户名已存在")
            db.add(User(username=args.username, display_name=args.name, password_hash=hash_password(password), is_admin=True))
            db.commit()
        print(f"管理员 {args.username} 已创建")


if __name__ == "__main__":
    main()
