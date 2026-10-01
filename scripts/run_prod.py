"""Start the prebuilt single-port server; no Node dependency at runtime."""
import argparse
from pathlib import Path
import subprocess
import sys
import os
import asyncio
from contextlib import suppress

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def parse_args(arguments=None):
    parser = argparse.ArgumentParser(description="启动 SeedLab 单端口服务（请先构建前端）。")
    parser.add_argument("--host", default="127.0.0.1", help="默认仅本机访问；局域网可指定 0.0.0.0")
    parser.add_argument("--port", type=int, default=8848)
    parser.add_argument("--web-root", type=Path, help="已构建前端目录；相对路径以项目根目录为基准")
    parser.add_argument("--stop-file", type=Path, help="本机控制中心的临时停止信号文件")
    args = parser.parse_args(arguments)
    if not 1 <= args.port <= 65535:
        parser.error("端口须为 1 至 65535。")
    return args


async def watch_stop_file(server, stop_file: Path, interval: float = 0.25):
    while not server.should_exit:
        if stop_file.is_file():
            server.should_exit = True
            return
        await asyncio.sleep(interval)


async def serve_with_stop_file(server, stop_file: Path):
    watcher = asyncio.create_task(watch_stop_file(server, stop_file))
    try:
        await server.serve()
    finally:
        watcher.cancel()
        with suppress(asyncio.CancelledError):
            await watcher
        stop_file.unlink(missing_ok=True)


def main(arguments=None) -> int:
    args = parse_args(arguments)
    if not PYTHON.is_file():
        print("Python 环境缺失，请先创建 .venv 并安装 backend 依赖。", flush=True)
        return 1
    if Path(sys.executable).resolve() != PYTHON.resolve():
        with subprocess.Popen([str(PYTHON), str(Path(__file__).resolve()),
                               *(sys.argv[1:] if arguments is None else arguments)], cwd=ROOT) as process:
            try:
                return process.wait()
            except KeyboardInterrupt:
                # The same console sends Ctrl+C to the server too. Let Uvicorn
                # finish shutdown rather than killing it immediately.
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait()
                return 0
    os.environ["SEEDLAB_ENV"] = "production"
    if args.web_root is not None:
        os.environ["SEEDLAB_WEB_ROOT"] = str(args.web_root)
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        import uvicorn
        from app.core.config import get_settings
        get_settings.cache_clear()
        web_root = get_settings().web_root
    except ImportError:
        print("Python 依赖不完整，请先安装 backend 依赖。", flush=True)
        return 1
    if not (web_root / "index.html").is_file():
        print(f"前端生产文件缺失：{web_root / 'index.html'}。请先运行 scripts/build_production.ps1。", flush=True)
        return 1
    stop_file = args.stop_file.resolve() if args.stop_file else None
    if stop_file and stop_file.exists():
        print("停止信号已存在，服务未启动。请重新从控制中心启动。", flush=True)
        return 1
    # Relative database/token paths retain the same backend cwd as run_dev.
    os.chdir(ROOT / "backend")
    print(f"前端目录：{web_root}\n正在检查并升级数据库……", flush=True)
    try:
        migration = subprocess.run([str(PYTHON), "-m", "alembic", "upgrade", "head"], check=False,
                                   creationflags=subprocess.CREATE_NO_WINDOW if stop_file and os.name == "nt" else 0)
        if migration.returncode:
            print("数据库升级失败，服务未启动。请检查上方错误并保留现有数据库。", flush=True)
            return migration.returncode
        url_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
        print(f"SeedLab 地址：http://{url_host}:{args.port}\n监听：{args.host}:{args.port}\n按 Ctrl+C 停止服务。", flush=True)
        if stop_file:
            server = uvicorn.Server(uvicorn.Config("app.main:app", host=args.host, port=args.port, workers=1))
            asyncio.run(serve_with_stop_file(server, stop_file))
        else:
            uvicorn.run("app.main:app", host=args.host, port=args.port, reload=False, workers=1)
    except KeyboardInterrupt:
        print("SeedLab 已停止。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
