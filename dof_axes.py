"""Visual guide to 3 DOF, 6 DOF, and 9 DOF IMU axes.

    python dof_axes.py
"""

from __future__ import annotations

import math
import sys

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

BG = QColor("#0c1016")
CARD = QColor("#151b24")
TEXT = QColor("#e8edf4")
MUTED = QColor("#8e9aab")
DIM = QColor("#6f7c8d")
AMBER = QColor("#e4b15a")
TEAL = QColor("#6fbfb8")
PERI = QColor("#9eb6e0")
MAG = QColor("#d2a4de")

STYLESHEET = """
QWidget#root { background: #0c1016; }
QFrame#card {
    background: #151b24;
    border: 1px solid #2a3344;
    border-radius: 18px;
}
QLabel#wordmark {
    color: #e8edf4;
    font-size: 18px;
    font-weight: 650;
    letter-spacing: 2px;
}
QLabel#subtitle, QLabel#note { color: #6f7c8d; font-size: 12px; }
QLabel#section {
    color: #e8edf4;
    font-size: 15px;
    font-weight: 650;
    letter-spacing: 1px;
}
QLabel#kind { color: #8e9aab; font-size: 12px; }
QLabel#bullet { color: #c5ceda; font-size: 12px; }
QLabel#key { color: #8e9aab; font-size: 12px; }
"""


def font(point_size: float, weight=QFont.Weight.Normal) -> QFont:
    face = QFont("Segoe UI")
    face.setPointSizeF(point_size)
    face.setWeight(weight)
    return face


def project(x: float, y: float, z: float, origin: QPointF, scale: float) -> QPointF:
    c = math.cos(math.radians(30))
    s = math.sin(math.radians(30))
    return QPointF(origin.x() + (x - y) * c * scale, origin.y() + (x + y) * s * scale - z * scale)


def draw_arrow(painter: QPainter, start: QPointF, end: QPointF, color: QColor, width: float = 2.8, dashed: bool = False) -> None:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    if dashed:
        pen.setStyle(Qt.PenStyle.DashLine)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawLine(start, end)
    angle = math.atan2(end.y() - start.y(), end.x() - start.x())
    length = 12.0
    spread = 0.42
    left = QPointF(end.x() - length * math.cos(angle - spread), end.y() - length * math.sin(angle - spread))
    right = QPointF(end.x() - length * math.cos(angle + spread), end.y() - length * math.sin(angle + spread))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPolygon(QPolygonF([end, left, right]))


def draw_label(painter: QPainter, anchor: QPointF, away: QPointF, text: str, color: QColor, nudge: QPointF = QPointF(0, 0)) -> None:
    dx = anchor.x() - away.x()
    dy = anchor.y() - away.y()
    length = math.hypot(dx, dy) or 1.0
    pos = QPointF(anchor.x() + dx / length * 18 + nudge.x(), anchor.y() + dy / length * 16 + nudge.y())
    painter.setPen(color)
    painter.setFont(font(9, QFont.Weight.DemiBold))
    painter.drawText(QRectF(pos.x() - 26, pos.y() - 10, 52, 20), Qt.AlignmentFlag.AlignCenter, text)


class DofView(QWidget):
    """Isometric sensor. 3 = acceleration, 6 = plus gyro, 9 = plus magnetometer."""

    def __init__(self, dof: int) -> None:
        super().__init__()
        self.dof = dof
        self._phase = 24.0
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._timer = QTimer(self)
        self._timer.setInterval(32)
        self._timer.timeout.connect(self._tick)
        if dof >= 6:
            self._timer.start()

    def _tick(self) -> None:
        self._phase = (self._phase + 1.1) % 360.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.fillRect(self.rect(), CARD)

        w, h = float(self.width()), float(self.height())
        if w < 40 or h < 40:
            return
        scale = min(w, h) * (0.27 if self.dof == 9 else 0.30)
        origin = QPointF(w * 0.46, h * 0.56) if self.dof == 9 else QPointF(w * 0.50, h * 0.58)
        if self.dof == 9:
            self._paint_nine(painter, origin, scale)
            return
        self._board(painter, origin, scale)
        self._linear(painter, origin, scale)
        if self.dof >= 6:
            self._rotations(painter, origin, scale)

    def _board(self, painter: QPainter, origin: QPointF, scale: float, yaw: float = 0.0) -> None:
        def spin(point: tuple[float, float, float]) -> tuple[float, float, float]:
            x, y, z = point
            c, s = math.cos(yaw), math.sin(yaw)
            return (x * c - y * s, x * s + y * c, z)

        top = [spin(p) for p in ((-1.15, -0.72, 0.16), (1.15, -0.72, 0.16), (1.15, 0.72, 0.16), (-1.15, 0.72, 0.16))]
        bottom = [spin(p) for p in ((-1.15, -0.72, 0.0), (1.15, -0.72, 0.0), (1.15, 0.72, 0.0), (-1.15, 0.72, 0.0))]
        shadow = project(0, 0.15, -0.05, origin, scale)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 70))
        painter.drawEllipse(QRectF(shadow.x() - scale * 1.15, shadow.y() - scale * 0.28, scale * 2.3, scale * 0.62))

        def poly(pts: list[tuple[float, float, float]]) -> QPolygonF:
            return QPolygonF([project(*p, origin, scale) for p in pts])

        painter.setBrush(QColor("#121820"))
        for i in range(4):
            j = (i + 1) % 4
            painter.drawPolygon(poly([bottom[i], bottom[j], top[j], top[i]]))
        grad = QLinearGradient(project(-1.15, -0.72, 0.16, origin, scale), project(1.15, 0.72, 0.16, origin, scale))
        grad.setColorAt(0.0, QColor("#243044"))
        grad.setColorAt(1.0, QColor("#18202c"))
        painter.setBrush(grad)
        painter.setPen(QPen(QColor("#3a465c"), 1.2))
        painter.drawPolygon(poly(top))

        chip = [spin(p) for p in ((-0.28, -0.22, 0.16), (0.28, -0.22, 0.16), (0.28, 0.22, 0.16), (-0.28, 0.22, 0.16))]
        painter.setBrush(QColor("#10161f"))
        painter.setPen(QPen(QColor("#465268"), 1.0))
        painter.drawPolygon(poly(chip))
        center = project(0, 0, 0.16, origin, scale)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e8edf4"))
        painter.drawEllipse(center, 3.0, 3.0)

    def _linear(self, painter: QPainter, origin: QPointF, scale: float) -> None:
        z0 = 0.16
        axes = (
            ((0, 0, z0), (1.45, 0, z0), AMBER, "AX", QPointF(8, 6)),
            ((0, 0, z0), (0, 1.35, z0), TEAL, "AY", QPointF(-8, 6)),
            ((0, 0, z0), (0, 0, z0 + 1.55), PERI, "AZ", QPointF(0, -12)),
        )
        center = project(0, 0, z0, origin, scale)
        for start, end, color, name, nudge in axes:
            a = project(*start, origin, scale)
            b = project(*end, origin, scale)
            draw_arrow(painter, a, b, color, 3.0)
            draw_label(painter, b, center, name, color, nudge)

    def _rotations(self, painter: QPainter, origin: QPointF, scale: float) -> None:
        specs = (
            ("x", AMBER, "GX", (0.15, -1.05, 1.35)),
            ("y", TEAL, "GY", (-1.15, 0.15, 1.45)),
            ("z", PERI, "GZ", (1.05, 0.95, 0.42)),
        )
        for axis, color, name, label_at in specs:
            points = []
            for step in range(0, 42):
                angle = math.radians(self._phase + step * 7.2)
                radius = 0.78
                if axis == "z":
                    x, y, z = radius * math.cos(angle), radius * math.sin(angle), 0.38
                elif axis == "x":
                    x, y, z = 0.0, radius * math.cos(angle), 0.62 + radius * math.sin(angle)
                else:
                    x, y, z = radius * math.cos(angle), 0.0, 0.62 + radius * math.sin(angle)
                points.append(project(x, y, z, origin, scale))
            pen = QPen(color, 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath(points[0])
            for point in points[1:]:
                path.lineTo(point)
            painter.drawPath(path)
            draw_arrow(painter, points[-2], points[-1], color, 2.2)
            spot = project(*label_at, origin, scale)
            painter.setPen(color)
            painter.setFont(font(9, QFont.Weight.DemiBold))
            painter.drawText(QRectF(spot.x() - 16, spot.y() - 10, 32, 18), Qt.AlignmentFlag.AlignCenter, name)

    def _paint_nine(self, painter: QPainter, origin: QPointF, scale: float) -> None:
        """Sensor axes yaw. The Earth's field arrow stays in one world direction."""
        yaw = math.radians(self._phase * 0.65)
        self._board(painter, origin, scale, yaw)

        # Fixed world direction: magnetic north. It is not attached to the board.
        north = (0.25, -1.0)
        length = math.hypot(*north)
        nx, ny = north[0] / length, north[1] / length
        tail = project(-1.15 * nx, -1.15 * ny, 0.78, origin, scale)
        tip = project(1.85 * nx, 1.85 * ny, 0.78, origin, scale)
        draw_arrow(painter, tail, tip, MAG, 3.4)
        painter.setPen(MAG)
        painter.setFont(font(9, QFont.Weight.DemiBold))
        painter.drawText(QRectF(tip.x() - 64, tip.y() - 22, 60, 18), Qt.AlignmentFlag.AlignRight, "NORTH")

        def spun(x: float, y: float, z: float) -> tuple[float, float, float]:
            c, s = math.cos(yaw), math.sin(yaw)
            return (x * c - y * s, x * s + y * c, z)

        z0 = 0.16
        center = project(*spun(0, 0, z0), origin, scale)
        axes = (
            (1.15, 0.0, z0, "MX"),
            (0.0, 1.05, z0, "MY"),
            (0.0, 0.0, z0 + 1.15, "MZ"),
        )
        for x, y, z, name in axes:
            end = project(*spun(x, y, z), origin, scale)
            draw_arrow(painter, center, end, MAG, 2.2, dashed=True)
            draw_label(painter, end, center, name, MAG)

        # Heading is the wedge between the sensor's MX axis and north, not a second yaw.
        north_angle = math.atan2(ny, nx)
        delta = (north_angle - yaw + math.pi) % (2.0 * math.pi) - math.pi
        wedge = []
        for step in range(19):
            angle = yaw + delta * step / 18.0
            wedge.append(project(0.62 * math.cos(angle), 0.62 * math.sin(angle), 0.32, origin, scale))
        pen = QPen(QColor("#f4e1c1"), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(wedge[0])
        for point in wedge[1:]:
            path.lineTo(point)
        painter.drawPath(path)
        mid = yaw + delta * 0.5
        spot = project(0.95 * math.cos(mid), 0.95 * math.sin(mid), 0.32, origin, scale)
        painter.setFont(font(8, QFont.Weight.DemiBold))
        painter.drawText(QRectF(spot.x() - 34, spot.y() - 18, 68, 28), Qt.AlignmentFlag.AlignCenter, f"{abs(math.degrees(delta)):.0f}°\nto north")


class Guide(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("IMU Degrees of Freedom")
        self.resize(1180, 760)
        self.setMinimumSize(980, 640)
        root = QWidget()
        root.setObjectName("root")
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(14)

        title = QLabel("3 DOF, 6 DOF, AND 9 DOF")
        title.setObjectName("wordmark")
        subtitle = QLabel("Solid arrows are acceleration. Curved arrows are rotation. Heading is the yaw angle measured from north, shown as the cream wedge.")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)

        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(self._panel(
            3,
            "3 DOF",
            "Accelerometer",
            [
                "AX, AY, and AZ are linear acceleration, in g.",
                "Sitting still, the upward axis reads about 1 g because of gravity.",
            ],
        ))
        row.addWidget(self._panel(
            6,
            "6 DOF",
            "Accelerometer + gyroscope",
            [
                "GX, GY, and GZ are rotation rate around those same axes, in °/s.",
                "Yaw is only the spin about Z. This panel has no north to measure it from.",
            ],
        ))
        row.addWidget(self._panel(
            9,
            "9 DOF",
            "Accelerometer + gyroscope + magnetometer",
            [
                "Nine means nine readings: 3 acceleration + 3 rotation + MX, MY, and MZ.",
                "The cream wedge is not another sensor. It is computed from those three magnetic axes.",
            ],
        ))
        outer.addLayout(row, 1)

        note = QLabel("The instrument panel for this project plots the 6 DOF set: AX AY AZ and GX GY GZ.")
        note.setObjectName("note")
        outer.addWidget(note)
        self.setStyleSheet(STYLESHEET)

    def _panel(self, dof: int, title: str, kind: str, lines: list[str]) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        heading = QLabel(title)
        heading.setObjectName("section")
        caption = QLabel(kind)
        caption.setObjectName("kind")
        layout.addWidget(heading)
        layout.addWidget(caption)
        layout.addWidget(DofView(dof), 1)
        for line in lines:
            bullet = QLabel(line)
            bullet.setObjectName("bullet")
            bullet.setWordWrap(True)
            layout.addWidget(bullet)
        return card


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    window = Guide()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
