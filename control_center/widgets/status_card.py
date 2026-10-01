from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy


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
        title_label = label(title, "muted")
        title_label.setFixedHeight(18)
        self.box.addWidget(title_label)
        self.value = label(value, "value", True)
        self.detail = label(detail, "muted", True)
        self.value.setMinimumHeight(34)
        self.value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.detail.setFixedHeight(32)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.box.addWidget(self.value, 1)
        self.box.addWidget(self.detail)


class StatusCardRow(QWidget):
    def __init__(self, cards):
        super().__init__()
        self.cards = tuple(cards)
        self.box = QHBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(14)
        for card in self.cards:
            self.box.addWidget(card, 1)

    def resizeEvent(self, event):
        width = max(1, (event.size().width() - 14 * (len(self.cards) - 1)) // len(self.cards) - 44)
        height = max(32, *(card.detail.heightForWidth(width) for card in self.cards))
        for card in self.cards:
            card.detail.setFixedHeight(height)
        super().resizeEvent(event)
