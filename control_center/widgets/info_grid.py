from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget, QLayout, QSizePolicy

from .status_card import label


class InfoGrid(QWidget):
    """Two groups of aligned labels and values; stack on narrow screens."""

    def __init__(self, fields):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.grid = QGridLayout(self)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(18)
        self.values = {}
        self.entries = []
        self.columns = 0
        for key, title in fields:
            value = label("—", "fieldValue", True)
            self.values[key] = value
            self.entries.append((label(title, "fieldLabel"), value))
        self._arrange(2)

    def _arrange(self, columns):
        if self.columns == columns:
            return
        while self.grid.count():
            self.grid.takeAt(0)
        for column in range(4):
            self.grid.setColumnStretch(column, 0)
        for index, (title, value) in enumerate(self.entries):
            row, group = divmod(index, columns)
            self.grid.addWidget(title, row, group * 2, Qt.AlignmentFlag.AlignVCenter)
            self.grid.addWidget(value, row, group * 2 + 1)
        for group in range(columns):
            self.grid.setColumnStretch(group * 2 + 1, 1)
        self.columns = columns
        self.updateGeometry()

    def resizeEvent(self, event):
        self._arrange(2 if event.size().width() >= 640 else 1)
        super().resizeEvent(event)
