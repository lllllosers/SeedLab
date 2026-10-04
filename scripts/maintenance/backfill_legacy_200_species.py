"""Temporary-only validation entry point; shares the production fact core."""
from legacy_import_core import *

def temporary_database(path: Path) -> Path:
    path = path.resolve()
    temporary_root = Path(tempfile.gettempdir()).resolve()
    require(path.is_relative_to(temporary_root) and path.suffix.lower() == ".db",
            "仅允许系统临时目录内的一次性 .db 测试数据库；正式数据目录不可使用")
    require(not any(part.casefold() == "seedlabdata" for part in path.parts), "禁止访问正式 SeedLabData")
    require(not any((parent / name).exists() for parent in path.parents
                    for name in ("seedlab.json", "installation.json", "config/seedlab.json", "config/installation.json")),
            "目标属于运行中的数据目录，请改用一次性临时测试库")
    require(path.is_file(), "请先在系统临时目录准备迁移到当前版本且含负责人的空业务测试数据库")
    wal = Path(str(path) + "-wal")
    require(not wal.exists() or wal.stat().st_size == 0, "请先关闭临时测试库连接并完成写入，再运行核验")
    return path


def inspect_target(path: Path, owner: str) -> str:
    # Immutable read-only mode cannot create WAL/SHM files or change the DB.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        require(db.execute("SELECT version_num FROM alembic_version").fetchall() == [(REVISION,)],
                "测试数据库迁移版本不一致，请先更新临时测试库")
        occupied = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in BUSINESS_TABLES}
        require(not any(occupied.values()), "测试数据库已有业务数据，请另建空业务临时库；工具不会清空或覆盖")
        owners = db.execute("SELECT id FROM users WHERE (username=? OR id=?) AND is_active=1", (owner, owner)).fetchall()
        require(len(owners) == 1, "请指定临时测试库中唯一且可用的实验负责人")
        return owners[0][0]


def apply(data: LegacyData, path: Path, owner_id: str) -> dict:
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                with Session(bind=connection) as db:
                    require(all(connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar() == 0
                                for table in BUSINESS_TABLES), "临时库已有业务数据，请重新准备空业务库")
                    owner = db.get(User, owner_id)
                    require(owner is not None and owner.is_active, "临时库负责人不可用")
                    experiment = insert_legacy(db, data, owner_id)
                    database_report = reconcile_database(db, data, experiment)
                    workbook_report = reconcile_workbook(build(db, [experiment.id]), data)
                    result = {"experiment_code": experiment.code, "database": database_report, "workbook": workbook_report}
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="200份历史材料的导入能力验证；仅使用一次性临时测试库")
    parser.add_argument("--source", type=Path, required=True, help="原始 Excel 绝对路径（只读）")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--database", type=Path, help="系统临时目录内已迁移的空业务 .db 测试库")
    target.add_argument("--data-root", type=Path, help="系统临时目录内的一次性测试目录，数据库为 seedlab.db")
    parser.add_argument("--owner", required=True, help="临时库中已有负责人的用户名或身份")
    parser.add_argument("--apply", action="store_true", help="明确写入临时测试库；默认只读核验")
    args = parser.parse_args(argv)
    try:
        data = read_source(args.source)
        path = temporary_database(args.database if args.database else args.data_root / "seedlab.db")
        owner_id = inspect_target(path, args.owner)
        result = {"status": "PASS", "mode": "apply" if args.apply else "dry-run",
                  "source_sha256": SOURCE_SHA256, "source": data.metrics}
        if args.apply:
            result.update(apply(data, path, owner_id))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f"核验停止：{exc}", file=sys.stderr)
    except (sqlite3.Error, SQLAlchemyError):
        print("核验停止：临时测试库无法读取或写入。请检查迁移版本、负责人和空业务状态；未完成的写入已回滚。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
