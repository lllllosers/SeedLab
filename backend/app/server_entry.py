"""One server entry point; suitable for a future standalone SeedLabServer.exe."""
import argparse
import asyncio
from contextlib import ExitStack, suppress
import os
import json
from pathlib import Path

def upgrade_database(*args, **kwargs):
    from app.services.database_upgrade import prepare_database_for_startup as upgrade
    return upgrade(*args, **kwargs)


def parse_args(arguments=None):
    parser = argparse.ArgumentParser(description="启动 SeedLab 单端口服务（请先构建前端）。")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8848)
    parser.add_argument("--web-root", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--bootstrap-token", type=Path)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--cookie-secure", choices=("true", "false"))
    parser.add_argument("--migration-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--access-mode", choices=("local", "lan", "remote"))
    parser.add_argument("--recover-from", type=Path, help="停止服务后，从选定备份恢复数据库，不启动服务")
    parser.add_argument("--confirm-stopped", action="store_true", help="明确确认 SeedLab 和数据库工具已停止")
    parser.add_argument("--existing-data", action="store_true")
    parser.add_argument("--candidate-id")
    parser.add_argument("--candidate-stop", type=Path)
    args = parser.parse_args(arguments)
    if not 1 <= args.port <= 65535:
        parser.error("端口须为 1 至 65535。")
    return args


async def watch_stop_file(server, stop_file, interval=0.25, additional=None):
    while not server.should_exit:
        if stop_file.is_file() or (additional is not None and additional.is_file()):
            server.should_exit = True
            return
        await asyncio.sleep(interval)


async def serve_with_stop_file(server, stop_file, additional=None):
    watcher = asyncio.create_task(watch_stop_file(server, stop_file, additional=additional))
    try:
        await server.serve()
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        stop_file.unlink(missing_ok=True)


def main(arguments=None):
    args = parse_args(arguments)
    if args.candidate_id:
        import re
        if (not re.fullmatch(r"[0-9a-f]{32}", args.candidate_id) or args.candidate_stop is None
                or not args.candidate_stop.is_absolute() or args.candidate_stop.parent.name != args.candidate_id
                or args.candidate_stop.name != "stop.request"):
            print("升级验证信息不完整，服务未启动。", flush=True)
            return 1
    from app.core.config import ROOT, Settings, get_settings
    if args.recover_from is not None:
        if (args.data_root is None or args.database is None or
                args.database.absolute() != (args.data_root / "data/seedlab.db").absolute()):
            print("恢复须明确指定完整数据目录及其中的实验数据库，原文件尚未替换。", flush=True)
            return 1
        from app.recovery import main as recover
        command = ["--data-root", str(args.data_root), "--snapshot", str(args.recover_from),
                   "--migration-root", str(args.migration_root or ROOT / "backend/alembic")]
        if args.confirm_stopped:
            command.append("--confirm-stopped")
        return recover(command)
    # Explicit production roots bypass repository .env; source-run defaults keep
    # the established development paths, anchored without changing cwd.
    defaults = Settings(_env_file=None) if args.database is not None else Settings()
    database = args.database.resolve() if args.database else None
    database_url = "sqlite:///" + database.as_posix() if database else defaults.seedlab_database_url
    if database is None and database_url.startswith("sqlite:///") and ":memory:" not in database_url:
        legacy = Path(database_url.removeprefix("sqlite:///"))
        database = (ROOT / "backend" / legacy).resolve()
        database_url = "sqlite:///" + database.as_posix()
    token = (args.bootstrap_token or ROOT / "backend" / defaults.seedlab_bootstrap_token_path).resolve()
    data_root = args.data_root.resolve() if args.data_root else (database.parent.parent if database else None)
    if args.data_root and (args.database is None or args.bootstrap_token is None
                          or not database.is_relative_to(data_root) or not token.is_relative_to(data_root)):
        print("数据目录与数据库、初始化码位置不一致，服务未启动。请从控制中心检查部署位置。", flush=True)
        return 1
    web = (args.web_root if args.web_root is not None else defaults.web_root)
    web = (ROOT / web).resolve()
    migration_root = args.migration_root.resolve() if args.migration_root else ROOT / "backend/alembic"
    if not (web / "index.html").is_file():
        print(f"前端生产文件缺失：{web / 'index.html'}。请先构建前端。", flush=True)
        return 1
    stop = args.stop_file.resolve() if args.stop_file else None
    if stop and stop.exists():
        print("停止信号已存在，服务未启动。请重新从控制中心启动。", flush=True)
        return 1
    if database is not None:
        database.parent.mkdir(parents=True, exist_ok=True)
    os.environ.update(SEEDLAB_ENV="production", SEEDLAB_DATABASE_URL=database_url,
        SEEDLAB_BOOTSTRAP_TOKEN_PATH=str(token), SEEDLAB_WEB_ROOT=str(web),
        SEEDLAB_COOKIE_SECURE=args.cookie_secure or str(defaults.seedlab_cookie_secure).lower())
    get_settings.cache_clear()
    print(f"前端目录：{web}\n正在检查并升级数据库……", flush=True)
    from app.services.database_upgrade import database_lease, UpgradeError
    with ExitStack() as startup:
        try:
            lease = startup.enter_context(database_lease(database_url))
            upgrade_database(database_url, migration_root, lease=lease,
                backup_root=data_root / "backups" if data_root else None,
                allow_create=not args.existing_data and not (data_root and (data_root / "config/seedlab.json").exists()))
        except UpgradeError as error:
            print(f"数据库启动未通过：{error}", flush=True)
            return 1
        except Exception:
            import traceback
            traceback.print_exc()
            print("数据库升级失败，服务未启动。请检查日志并保留现有数据库。", flush=True)
            return 1
        return run_prepared_server(args, data_root, stop)


def run_prepared_server(args, data_root, stop):
    # The caller holds the database lease until Uvicorn has fully stopped.
    from app.core.config import get_settings
    from app.services.runtime_identity import deployment_identity, IdentityError
    mode = args.access_mode or ("lan" if args.host == "0.0.0.0" else
                                "remote" if args.cookie_secure == "true" else "local")
    if args.host != ("0.0.0.0" if mode == "lan" else "127.0.0.1"):
        print("访问方式与监听地址不一致，服务未启动。请检查访问设置。", flush=True)
        return 1
    try:
        identity = deployment_identity(data_root) if data_root else None
    except IdentityError as error:
        print(str(error), flush=True)
        return 1
    runtime = ({"instance_id": identity.instance_id, "data_root": str(identity.data_root),
                "probe_token": identity.probe_token, "port": args.port,
                "access_mode": mode, "bind_host": args.host, "pid": os.getpid()} if identity else None)
    if runtime is not None and args.candidate_id:
        runtime["candidate_id"] = args.candidate_id
    os.environ["SEEDLAB_RUNTIME_INFO"] = json.dumps(runtime)
    get_settings.cache_clear()
    import uvicorn
    from app.main import create_app
    application = create_app(get_settings())
    host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    print(f"SeedLab 地址：http://{host}:{args.port}\n监听：{args.host}:{args.port}\n按 Ctrl+C 停止服务。", flush=True)
    try:
        if stop:
            server = uvicorn.Server(uvicorn.Config(application, host=args.host, port=args.port, workers=1))
            asyncio.run(serve_with_stop_file(server, stop, additional=args.candidate_stop))
        else:
            uvicorn.run(application, host=args.host, port=args.port, reload=False, workers=1)
    except KeyboardInterrupt:
        print("SeedLab 已停止。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
