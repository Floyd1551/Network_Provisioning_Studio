"""Render the source SVG into a multi-resolution Windows icon using Qt."""
import struct
from pathlib import Path
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

app = QApplication([])
assets = Path(__file__).resolve().parents[1] / "src/switch_configurator/assets"
renderer = QSvgRenderer(str(assets / "app.svg"))
if not renderer.isValid(): raise RuntimeError("Invalid icon SVG")
frames = []
for size in (16, 24, 32, 48, 64, 128, 256):
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image); renderer.render(painter); painter.end()
    buffer = QBuffer(); buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"): raise RuntimeError("Icon rendering failed")
    frames.append((size, bytes(buffer.data())))
offset = 6 + 16 * len(frames)
entries = []
for size, data in frames:
    entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
    offset += len(data)
(assets / "app.ico").write_bytes(struct.pack("<HHH", 0, 1, len(frames)) + b"".join(entries) + b"".join(data for _, data in frames))
print(assets / "app.ico")
