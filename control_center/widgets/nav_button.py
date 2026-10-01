from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QPushButton


class NavButton(QPushButton):
    """Small local SVG icons with the same active colour as the navigation."""

    def __init__(self, text, icon_name, slot):
        super().__init__(text)
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(18, 18))
        source = (Path(__file__).parents[1] / "assets" / f"{icon_name}.svg").read_text(encoding="utf-8")
        icon = QIcon()
        for state, colour in ((QIcon.State.Off, "#66768a"), (QIcon.State.On, "#447db9")):
            renderer = QSvgRenderer(QByteArray(source.replace("currentColor", colour).encode("utf-8")))
            for size in (18, 23, 27, 36, 54, 72):
                pixmap = QPixmap(size, size)
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                renderer.render(painter)
                painter.end()
                icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
        self.setIcon(icon)
        self.clicked.connect(slot)
