"""A user/session-local Qt IPC endpoint; no persistent lock files."""
import getpass
import hashlib
import os

from PySide6.QtCore import QObject, Signal, QEventLoop, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def instance_name():
    identity = "|".join((getpass.getuser(), os.environ.get("USERDOMAIN", ""), os.environ.get("SESSIONNAME", "")))
    return "SeedLab-Control-" + hashlib.sha256(identity.encode()).hexdigest()[:24]


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, name=None, parent=None):
        super().__init__(parent)
        self.name = name or instance_name()
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self.receive)
        self.sockets = set()
        self.owned = False

    def notify(self):
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if not socket.waitForConnected(1000):
            error = socket.error()
            socket.abort()
            if error == QLocalSocket.LocalSocketError.SocketAccessError:
                raise OSError("无法访问当前用户的控制中心，请检查当前 Windows 用户会话。")
            return False
        socket.write(b"activate\n")
        socket.flush()
        # Wait for the owner to consume the message before the second process
        # exits. A bounded Qt loop also permits isolated same-process IPC tests.
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        socket.readyRead.connect(loop.quit)
        socket.disconnected.connect(loop.quit)
        timeout.start(1000)
        loop.exec()
        timeout.stop()
        socket.disconnectFromServer()
        return True

    def acquire(self):
        if self.notify():
            return False
        if self.server.listen(self.name):
            self.owned = True
            return True
        # A concurrent instance may have won the listen race. Never remove a
        # live endpoint; only clear a stale endpoint after another failed probe.
        if self.notify():
            return False
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            if self.notify():
                return False
            raise OSError("控制中心无法建立本机连接，请关闭后重试。")
        self.owned = True
        return True

    def receive(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.sockets.add(socket)
            socket.readyRead.connect(lambda item=socket: self.read(item))
            socket.disconnected.connect(lambda item=socket: self.release(item))
            self.read(socket)

    def read(self, socket):
        if socket.canReadLine():
            if bytes(socket.readLine(32)).strip() == b"activate":
                self.activated.emit()
                socket.write(b"ok\n")
                socket.flush()
            socket.disconnectFromServer()

    def release(self, socket):
        self.sockets.discard(socket)
        socket.deleteLater()

    def close(self):
        if self.owned:
            self.server.close()
            QLocalServer.removeServer(self.name)
            self.owned = False
