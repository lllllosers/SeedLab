"""Regenerate the Windows brand assets from the existing SeedLab SVG."""
from pathlib import Path
import struct

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]


def main():
    assets = ROOT / "control_center/assets"
    renderer = QSvgRenderer(str(assets / "seedlab.svg"))
    if not renderer.isValid():
        raise RuntimeError("SeedLab SVG is invalid")
    frames = []
    for size in (16, 24, 32, 48, 64, 128, 256):
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        encoded = QByteArray()
        buffer = QBuffer(encoded)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError("Brand image encoding failed")
        frames.append((size, bytes(encoded)))
    offset = 6 + 16 * len(frames)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(frames)))
    for size, png in frames:
        directory.extend(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset))
        offset += len(png)
    (assets / "SeedLab.ico").write_bytes(bytes(directory) + b"".join(png for _, png in frames))
    (assets / "SeedLab.png").write_bytes(frames[-1][1])
    print("Generated SeedLab.ico (16-256 px) and notification PNG from seedlab.svg")


if __name__ == "__main__":
    main()
