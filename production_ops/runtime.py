"""Candidate Control Center lifecycle; its own Server remains under its ownership."""
import json
from pathlib import Path
import subprocess
import time
from urllib.request import Request, build_opener, HTTPRedirectHandler

from . import OperationsError
from .deployment import CENTER, SERVER, LAUNCHER, ordinary, read_json
from .windows import process_programs, require_stopped


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class CandidateRuntime:
    def __init__(self, store, *, isolated=False, timeout=45):
        self.store, self.isolated, self.timeout = store, isolated, timeout
        self.process = None
        self.output = None

    def request_handoff(self, path, program):
        if path is not None:
            path = ordinary(path)
            if path.parent != self.store.root / "Updates" or not path.name.startswith("handoff-"):
                raise OperationsError("控制中心交接位置不正确，请重新打开系统升级。")
            path.touch(exist_ok=False)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    require_stopped(program)
                    return
                except OperationsError:
                    time.sleep(0.2)
            raise OperationsError("控制中心尚未退出，请等待备份和当前操作结束，然后重试。")
        require_stopped(program)

    def start(self, state):
        pending = state["pending"]
        self.stop_path = self.store.job(pending) / "stop.request"
        if self.stop_path.exists():
            raise OperationsError("本次候选验证已经停止，请先恢复原版本后重新选择升级包。")
        program = Path(pending["target"]["program_root"])
        command = [str(program / CENTER), "--deployment-root", str(self.store.root),
                   "--data-root", state["data_root"], "--candidate-id", pending["id"]]
        if self.isolated:
            command.append("--isolated")
        self.output = (self.store.job(pending) / "candidate-output.log").open("ab")
        try:
            self.process = subprocess.Popen(command, cwd=program, stdout=self.output, stderr=subprocess.STDOUT,
                                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            self.output.close()
            raise

    def healthy(self, state):
        from control_center.config_store import DeploymentSettings
        data = Path(state["data_root"])
        settings = DeploymentSettings.from_dict(read_json(data / "config/seedlab.json"))
        identity = read_json(data / "config/instance.json")
        pending = state["pending"]
        opener = build_opener(NoRedirect())
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise OperationsError("新版本控制中心未能正常打开，尚未切换当前版本。")
            try:
                request = Request(settings.health_url + "/api/health", headers={"X-SeedLab-Control": identity["probe_token"]})
                with opener.open(request, timeout=1) as response:
                    payload = json.load(response)
                expected = {"status": "ok", "version": pending["target"]["version"],
                            "instance_id": identity["instance_id"], "candidate_id": pending["id"],
                            "port": settings.port, "access_mode": settings.access_mode, "bind_host": settings.bind_host}
                if (all(payload.get(key) == value for key, value in expected.items())
                        and Path(payload["data_root"]).resolve() == data.resolve()
                        and any(pid == payload["pid"] and path == Path(pending["target"]["program_root"]) / SERVER
                                for pid, path in process_programs())):
                    return
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.2)
        raise OperationsError("新版本运行检查未通过，尚未切换当前版本。请打开升级日志查看原因。")

    def stop(self, state):
        stop = self.store.job(state["pending"]) / "stop.request"
        stop.touch(exist_ok=True)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                require_stopped(state["pending"]["target"]["program_root"])
                if self.process is None or self.process.poll() is not None:
                    if self.output:
                        self.output.close()
                    return
            except OperationsError:
                pass
            time.sleep(0.2)
        raise OperationsError("新版本尚未完全停止，请保留数据与升级现场，停止控制中心和服务后再恢复。")

    def launch_current(self):
        command = [str(self.store.root / LAUNCHER), "--start-server"]
        if self.isolated:
            return  # Build smoke explicitly opens the current entry with isolated flags.
        subprocess.Popen(command, cwd=self.store.root, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
