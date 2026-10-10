"""Read-only path field that stays within the form and keeps the full value copyable."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout, QLabel, QPushButton, QSizePolicy


class PathDisplay(QWidget):
    def __init__(self, text=""):
        super().__init__()
        self.value = str(text)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setMinimumWidth(0)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.label, 1)
        copy = QPushButton("复制")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.value))
        layout.addWidget(copy)
        self.setText(text)

    def text(self):
        return self.value

    def setText(self, text):
        self.value = str(text)
        self.setToolTip(self.value)
        self.label.setText(self.label.fontMetrics().elidedText(self.value, Qt.TextElideMode.ElideMiddle, self.label.width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(self.value)
