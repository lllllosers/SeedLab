"""Administrative, explicit recovery entry; never uses a default database."""
import argparse
import logging
from pathlib import Path

from app.services.database_recovery import restore_database
from app.services.database_upgrade import UpgradeError


def main(arguments=None):
    parser = argparse.ArgumentParser(description="停止服务后，从核验备份恢复实验数据库；保留原数据库。")
    parser.add_argument("--data-root", type=Path, required=True, help="现有正式数据目录的完整路径")
    parser.add_argument("--snapshot", type=Path, required=True, help="选定数据库备份的完整路径")
    parser.add_argument("--migration-root", type=Path, required=True, help="兼容程序的数据库升级文件目录")
    parser.add_argument("--confirm-stopped", action="store_true", help="明确确认 SeedLab 和所有数据库工具已停止")
    args = parser.parse_args(arguments)
    if not all(path.is_absolute() for path in (args.data_root, args.snapshot, args.migration_root)):
        parser.error("数据、备份和升级文件位置均须填写完整路径。")
    try:
        result = restore_database("sqlite:///" + (args.data_root / "data/seedlab.db").as_posix(),
            args.snapshot, args.migration_root, backup_root=args.data_root / "backups",
            confirm_stopped=args.confirm_stopped)
    except (UpgradeError, OSError) as error:
        logging.getLogger("seedlab.recovery").exception("数据库恢复未完成")
        print(str(error) if isinstance(error, UpgradeError) else
              "恢复未完成，请保留当前文件，检查数据与备份目录的权限和可用空间后重试。", flush=True)
        return 1
    print(f"数据库已恢复。原数据库保留在：{result.preserved}。请使用与备份兼容的程序检查后再启动。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
