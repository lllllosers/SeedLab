from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout


def label(text, kind=None, wrap=False):
    item = QLabel(text)
    if kind:
        item.setObjectName(kind)
    item.setWordWrap(wrap)
    item.setMinimumWidth(0)
    item.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return item


class Card(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(22, 20, 22, 20)
        self.box.setSpacing(12)


class StatusCard(Card):
    def __init__(self, title, value="—", detail=""):
        super().__init__()
        self.box.addWidget(label(title, "muted"))
        self.value = label(value, "value", True)
        self.detail = label(detail, "muted", True)
        self.box.addWidget(self.value)
        self.box.addWidget(self.detail)
