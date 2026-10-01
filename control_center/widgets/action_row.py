from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget, QLayout, QSizePolicy


class ActionRow(QWidget):
    """Keep ordinary button widths and wrap only when the page gets narrow."""

    def __init__(self, buttons):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.buttons = tuple(buttons)
        self.columns = 0
        self.grid = QGridLayout(self)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)
        self._arrange(len(self.buttons))

    def _arrange(self, columns):
        if columns == self.columns:
            return
        while self.grid.count():
            self.grid.takeAt(0)
        for column in range(len(self.buttons) + 1):
            self.grid.setColumnStretch(column, 0)
        for index, button in enumerate(self.buttons):
            row, column = divmod(index, columns)
            self.grid.addWidget(button, row, column, Qt.AlignmentFlag.AlignLeft)
        self.grid.setColumnStretch(columns, 1)
        self.columns = columns
        self.updateGeometry()

    def resizeEvent(self, event):
        visible = [item for item in self.buttons if not item.isHidden()]
        widest = max((item.sizeHint().width() for item in visible), default=1)
        columns = min(len(self.buttons), max(1, (event.size().width() + 10) // (widest + 10)))
        self._arrange(columns)
        super().resizeEvent(event)
