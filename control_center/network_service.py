from dataclasses import dataclass, replace
import ipaddress
import json

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkInterface, QAbstractSocket, QNetworkAccessManager, QNetworkRequest, QNetworkReply

from app.version import VERSION
from .config_store import normalize_remote_url


MODE_LABELS = {"local": "仅本机使用", "lan": "局域网共享", "remote": "远程访问"}
VIRTUAL_NAMES = ("vmware", "virtualbox", "hyper-v", "vethernet", "docker", "wsl", "tailscale", "loopback")


@dataclass(frozen=True)
class LanAddress:
    name: str
    address: str
    other: bool = False


def usable_ipv4(value):
    try:
        address = ipaddress.IPv4Address(value)
        return not (address.is_loopback or address.is_unspecified or address.is_link_local or address.is_multicast or address.is_reserved)
    except ValueError:
        return False


def lan_addresses():
    addresses = []
    flags = QNetworkInterface.InterfaceFlag
    for interface in QNetworkInterface.allInterfaces():
        active = interface.flags()
        if not (active & flags.IsUp and active & flags.IsRunning) or active & flags.IsLoopBack:
            continue
        name = interface.humanReadableName() or interface.name()
        virtual = any(term in (name + " " + interface.name()).lower() for term in VIRTUAL_NAMES)
        for entry in interface.addressEntries():
            address = entry.ip()
            if address.protocol() == QAbstractSocket.NetworkLayerProtocol.IPv4Protocol and usable_ipv4(address.toString()):
                addresses.append(LanAddress(name, address.toString(), virtual))
    return sorted(set(addresses), key=lambda item: (item.other, not ipaddress.IPv4Address(item.address).is_private,
                                                   item.name.casefold(), int(ipaddress.IPv4Address(item.address))))


def resolve_lan(settings, addresses):
    if settings.access_mode != "lan":
        return settings, ""
    if settings.lan_address in {item.address for item in addresses}:
        return settings, ""
    if not addresses:
        return replace(settings, lan_address=None), "当前没有可用的局域网 IPv4 地址。"
    warning = "原局域网地址已不可用，已选择当前网络地址。" if settings.lan_address else "已选择当前推荐的局域网地址，请保存设置。"
    return replace(settings, lan_address=addresses[0].address), warning


def remote_result(payload, *, network_error=False):
    if network_error:
        return "unreachable", "当前无法连接远程地址"
    if not isinstance(payload, dict) or payload.get("status") != "ok" or not isinstance(payload.get("version"), str):
        return "wrong-site", "该地址没有连接到当前 SeedLab"
    if payload["version"] != VERSION:
        return "wrong-version", "远程地址连接到其他版本的 SeedLab"
    return "ok", "远程访问正常"


class RemoteChecker(QObject):
    changed = Signal()
    event = Signal(str)

    def __init__(self, logger, parent=None):
        super().__init__(parent)
        self.logger = logger
        self.network = QNetworkAccessManager(self)
        self.network.finished.connect(self._finished)
        self.reply = None
        self.url = None
        self.status = "unchecked"
        self.message = "尚未检测远程入口"
        self.manual = False
        self._last_result = None

    def check(self, url, *, manual=True):
        url = normalize_remote_url(url)
        if self.reply is not None:
            return
        self.url = url
        self.manual = manual
        self.status, self.message = "checking", "正在检测…"
        self.changed.emit()
        request = QNetworkRequest(QUrl(url + "/api/health"))
        request.setTransferTimeout(5000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        self.reply = self.network.get(request)
        # Never ignoreSslErrors: Qt's certificate and hostname verification stays enabled.

    def _finished(self, reply):
        if reply is not self.reply:
            reply.deleteLater()
            return
        self.reply = None
        error = reply.error() != QNetworkReply.NetworkError.NoError
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        try:
            payload = json.loads(bytes(reply.readAll())) if not error and status == 200 else None
        except (ValueError, UnicodeDecodeError):
            payload = None
        if error:
            self.logger.warning("远程入口检测失败：%s", reply.errorString())
        self.status, self.message = remote_result(payload, network_error=error and status is None)
        result = (self.url, self.status)
        if self.manual or result != self._last_result:
            self.event.emit(self.message + "。")
        self._last_result = result
        reply.deleteLater()
        self.changed.emit()

    def reset(self):
        self.stop()
        self.url = None
        self.status, self.message = "unchecked", "尚未检测远程入口"
        self._last_result = None
        self.changed.emit()

    def stop(self):
        if self.reply:
            reply, self.reply = self.reply, None
            reply.abort()
