"""Deployment settings, separate from development .env and business data."""
from dataclasses import asdict, dataclass
import ipaddress
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit, urlunsplit


class ConfigError(ValueError):
    pass


def normalize_remote_url(value):
    if not isinstance(value, str):
        raise ConfigError("远程访问地址必须使用 HTTPS。")
    value = value.strip().rstrip("/")
    if any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
        raise ConfigError("请填写有效的远程 HTTPS 根地址。")
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = parsed.hostname
    except ValueError as error:
        raise ConfigError("请检查远程地址及端口。") from error
    if parsed.scheme.lower() != "https":
        raise ConfigError("远程访问地址必须使用 HTTPS。")
    if not host or parsed.username is not None or parsed.password is not None or "?" in value or "#" in value or parsed.path:
        raise ConfigError("请填写 HTTPS 根地址，不要包含账号、路径、查询参数或片段。")
    if port is not None and not 1 <= port <= 65535:
        raise ConfigError("远程地址的端口必须在 1～65535 之间。")
    try:
        address = ipaddress.ip_address(host)
        host = f"[{address}]" if address.version == 6 else str(address)
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii").lower()
        except UnicodeError as error:
            raise ConfigError("请检查远程地址的主机名。") from error
        if len(host) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")):
            raise ConfigError("请检查远程地址的主机名。")
    return urlunsplit(("https", host + (f":{port}" if port is not None else ""), "", "", ""))


@dataclass(frozen=True)
class DeploymentSettings:
    schema_version: int = 1
    access_mode: str = "local"
    port: int = 8848
    lan_address: str | None = None
    remote_url: str | None = None
    auto_backup_enabled: bool = True
    auto_backup_retention: int = 14

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ConfigError("运行设置版本不受支持。")
        if self.access_mode not in ("local", "lan", "remote"):
            raise ConfigError("请选择有效的访问方式。")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ConfigError("监听端口必须在 1～65535 之间。")
        if self.lan_address is not None:
            try:
                if not isinstance(self.lan_address, str):
                    raise ValueError()
                ipaddress.IPv4Address(self.lan_address)
            except ValueError as error:
                raise ConfigError("请填写有效的局域网 IPv4 地址。") from error
        if self.remote_url is not None:
            object.__setattr__(self, "remote_url", normalize_remote_url(self.remote_url))
        if self.access_mode == "remote" and not self.remote_url:
            raise ConfigError("请先填写远程 HTTPS 地址。")
        if type(self.auto_backup_enabled) is not bool:
            raise ConfigError("请选择是否启用自动备份。")
        if type(self.auto_backup_retention) is not int or not 1 <= self.auto_backup_retention <= 90:
            raise ConfigError("自动备份保留份数必须在 1～90 之间。")

    @classmethod
    def from_dict(cls, values):
        if not isinstance(values, dict) or set(values) - set(cls.__dataclass_fields__):
            raise ConfigError("运行设置包含不支持的内容，请检查配置文件。")
        return cls(**values)

    def to_dict(self):
        return asdict(self)

    @property
    def bind_host(self):
        return "0.0.0.0" if self.access_mode == "lan" else "127.0.0.1"

    @property
    def cookie_secure(self):
        return self.access_mode == "remote"

    @property
    def health_url(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def user_url(self):
        if self.access_mode == "remote":
            return self.remote_url
        if self.access_mode == "lan":
            return f"http://{self.lan_address}:{self.port}" if self.lan_address else None
        return self.health_url


class ConfigStore:
    def __init__(self, path: Path, logger=None):
        self.path = path
        self.logger = logger
        self.settings = DeploymentSettings()
        self.warning = ""

    def load(self):
        self.warning = ""
        if not self.path.exists():
            self.settings = DeploymentSettings()
            return self.settings
        try:
            self.settings = DeploymentSettings.from_dict(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            self.settings = DeploymentSettings()
            self.warning = "运行设置无法读取，当前使用仅本机安全模式。请检查设置后主动保存。"
            if self.logger:
                self.logger.exception("运行设置读取失败，保留原文件并使用安全默认值")
        return self.settings

    def save(self, settings):
        settings = DeploymentSettings.from_dict(settings.to_dict())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".seedlab-", suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                json.dump(settings.to_dict(), output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        self.settings = settings
        self.warning = ""
