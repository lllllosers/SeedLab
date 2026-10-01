"""Non-business deployment identity; never stored in the experiment database."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import tempfile
from uuid import UUID, uuid4

from app.services.sqlite_backup import ordinary_path


class IdentityError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeIdentity:
    instance_id: str
    probe_token: str
    data_root: Path

    def matches(self, payload):
        try:
            return (payload.get("instance_id") == self.instance_id
                    and Path(payload["data_root"]).is_absolute()
                    and Path(payload["data_root"]).resolve() == self.data_root)
        except (KeyError, TypeError, ValueError, OSError):
            return False


def deployment_identity(data_root):
    root = Path(data_root).resolve()
    directory = root / "config"
    path = directory / "instance.json"
    for ancestor in (directory, *directory.parents):
        if ancestor.exists() and not ordinary_path(ancestor, directory=True):
            raise IdentityError("部署位置包含重定向目录，请保留数据并选择普通文件夹。")
    temporary = None
    try:
        if not path.exists():
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                             prefix=".instance-", suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                json.dump({"schema_version": 1, "instance_id": str(uuid4()),
                           "probe_token": secrets.token_urlsafe(32)}, output)
                output.flush()
                os.fsync(output.fileno())
            try:
                if os.name == "nt":
                    os.rename(temporary, path)  # Exclusive atomic publication on Windows.
                else:
                    os.link(temporary, path)
            except FileExistsError:
                pass  # Another process published the same deployment first.
        if not ordinary_path(path):
            raise ValueError("redirected identity")
        value = json.loads(path.read_text(encoding="utf-8"))
        if (set(value) != {"schema_version", "instance_id", "probe_token"}
                or type(value["schema_version"]) is not int or value["schema_version"] != 1
                or str(UUID(value["instance_id"])) != value["instance_id"]
                or not isinstance(value["probe_token"], str) or len(value["probe_token"]) < 32):
            raise ValueError("invalid identity")
        return RuntimeIdentity(value["instance_id"], value["probe_token"], root)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise IdentityError("部署标识无法准备或读取，请保留数据目录并检查写入权限及配置文件。") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
