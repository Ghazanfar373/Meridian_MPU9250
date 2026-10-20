"""IMU instrument panel.

Reads the 40-byte packets from working_imu_i2c.ino (57600 baud) and
draws attitude, heading, acceleration, and gyro gauges.

    pip install -r requirements.txt
    python imu_dashboard.py
"""

from __future__ import annotations

import math
import struct
import sys
import time

from PyQt6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QConicalGradient,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PyQt6.QtSerialPort import QSerialPort, QSerialPortInfo
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

PACKET_SIZE = 40
BG = QColor("#0c1016")
CARD = QColor("#151b24")
TEXT = QColor("#e8edf4")
MUTED = QColor("#8e9aab")
DIM = QColor("#6f7c8d")
AMBER = QColor("#e4b15a")
TEAL = QColor("#6fbfb8")
PERI = QColor("#9eb6e0")

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
    letter-spacing: 3px;
}
QLabel#subtitle, QLabel#note { color: #6f7c8d; font-size: 11px; }
QLabel#section {
    color: #8e9aab;
    font-size: 11px;
    font-weight: 650;
    letter-spacing: 2px;
}
QLabel#caption {
    color: #8e9aab;
    font-size: 10px;
    font-weight: 650;
    letter-spacing: 1.6px;
}
QLabel#value {
    color: #e8edf4;
    font-size: 26px;
    font-weight: 650;
}
QLabel#hz { color: #8e9aab; font-size: 12px; font-weight: 600; }
QPushButton {
    border-radius: 9px;
    padding: 8px 14px;
    font-weight: 650;
    min-height: 18px;
}
QPushButton#primary {
    background: #e4b15a;
    color: #1c1508;
    border: none;
}
QPushButton#primary:hover { background: #f0c56d; }
QPushButton#primary:pressed { background: #c9963d; }
QPushButton#ghost {
    background: transparent;
    color: #e8edf4;
    border: 1px solid #3a4558;
}
QPushButton#ghost:hover { background: #222a38; }
QPushButton#ghost:checked {
    background: #16302e;
    color: #8fd4ce;
    border: 1px solid #3d7c76;
}
QPushButton:disabled { color: #66707e; background: #171d27; border-color: #2a3344; }
QComboBox {
    background: #1b2230;
    color: #e8edf4;
    border: 1px solid #343e50;
    border-radius: 9px;
    padding: 7px 12px;
    min-width: 210px;
}
QComboBox:hover { border-color: #4c586c; }
QComboBox:focus { border-color: #e4b15a; }
QComboBox QAbstractItemView {
    background: #1b2230;
    color: #e8edf4;
    selection-background-color: #2c384c;
    selection-color: #e8edf4;
    border: 1px solid #3a4558;
    outline: 0;
    padding: 4px;
}
QToolTip {
    background: #1b2230;
    color: #e8edf4;
    border: 1px solid #3a4558;
    padding: 4px 8px;
}
"""


def make_font(point_size: float, weight=QFont.Weight.Normal, spacing: float = 0.0) -> QFont:
    font = QFont("Segoe UI")
    font.setPointSizeF(point_size)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return font


def ease(shown: float, target: float, gain: float = 0.34, circular: bool = False) -> tuple[float, bool]:
    if circular:
        delta = (target - shown + 180.0) % 360.0 - 180.0
    else:
        delta = target - shown
    if abs(delta) <= 0.04:
        return target, True
    return shown + delta * gain, False


def pt(cx: float, cy: float, deg_cw_from_up: float, radius: float) -> QPointF:
    rad = math.radians(deg_cw_from_up)
    return QPointF(cx + math.sin(rad) * radius, cy - math.cos(rad) * radius)


def circle_rect(cx: float, cy: float, radius: float) -> QRectF:
    return QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0)


def qt_arc(deg_cw_from_up: float) -> int:
    """Qt arc angle: 0 at 3 o'clock, counter-clockwise, in 1/16 degree."""
    return int(round((90.0 - deg_cw_from_up) * 16))


def marker(cx: float, cy: float, ang: float, radius: float, size: float, inward: bool) -> QPolygonF:
    rad = math.radians(ang)
    dx, dy = math.sin(rad), -math.cos(rad)
    px, py = -dy, dx
    tip_r = radius - size if inward else radius + size
    half = size * 0.55
    return QPolygonF(
        [
            QPointF(cx + dx * tip_r, cy + dy * tip_r),
            QPointF(cx + dx * radius + px * half, cy + dy * radius + py * half),
            QPointF(cx + dx * radius - px * half, cy + dy * radius - py * half),
        ]
    )


def paint_bezel(painter: QPainter, cx: float, cy: float, outer_r: float, inner_r: float) -> None:
    grad = QConicalGradient(cx, cy, -35)
    grad.setColorAt(0.00, QColor("#8e97a8"))
    grad.setColorAt(0.22, QColor("#323a4a"))
    grad.setColorAt(0.42, QColor("#d5dbe6"))
    grad.setColorAt(0.55, QColor("#2a3140"))
    grad.setColorAt(0.78, QColor("#7f8898"))
    grad.setColorAt(1.00, QColor("#8e97a8"))
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), outer_r, outer_r)
    path.addEllipse(QPointF(cx, cy), inner_r, inner_r)
    path.setFillRule(Qt.FillRule.OddEvenFill)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(grad)
    painter.drawPath(path)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
    painter.drawEllipse(QPointF(cx, cy), inner_r + 0.6, inner_r + 0.6)


def paint_glass(painter: QPainter, cx: float, cy: float, radius: float) -> None:
    painter.save()
    clip = QPainterPath()
    clip.addEllipse(QPointF(cx, cy), radius, radius)
    painter.setClipPath(clip, Qt.ClipOperation.ReplaceClip)
    grad = QLinearGradient(cx, cy - radius, cx, cy - radius * 0.15)
    grad.setColorAt(0.0, QColor(255, 255, 255, 34))
    grad.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(grad)
    painter.drawRect(QRectF(cx - radius, cy - radius, radius * 2.0, radius * 0.85))
    painter.restore()


def encode_packet(pitch: float, roll: float, yaw: float, ax: float, ay: float, az: float,
                  gx: float, gy: float, gz: float) -> bytes:
    body = struct.pack("<B9f", 36, pitch, roll, yaw, ax, ay, az, gx, gy, gz)
    checksum = 0
    for byte in body:
        checksum ^= byte
    return b"\xAA\x55" + body + bytes((checksum,))


class PacketParser:
    """Hunt for 0xAA 0x55 and accept only length-checked, XOR-checked frames."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def reset(self) -> None:
        self.buf.clear()

    def feed(self, data: bytes) -> list[tuple[float, ...]]:
        self.buf.extend(data)
        samples: list[tuple[float, ...]] = []
        while True:
            start = self.buf.find(b"\xAA\x55")
            if start < 0:
                if self.buf and self.buf[-1] == 0xAA:
                    del self.buf[:-1]
                else:
                    self.buf.clear()
                break
            if start:
                del self.buf[:start]
            if len(self.buf) < PACKET_SIZE:
                break
            frame = self.buf[:PACKET_SIZE]
            body = frame[2:39]
            checksum = 0
            for byte in body:
                checksum ^= byte
            if frame[2] == 36 and checksum == frame[39]:
                values = struct.unpack("<9f", frame[3:39])
                if all(math.isfinite(v) for v in values):
                    samples.append(values)
                del self.buf[:PACKET_SIZE]
            else:
                del self.buf[:1]
        if len(self.buf) > 2048:
            self.buf = self.buf[-1:]
        return samples


class SerialLink(QObject):
    sample = pyqtSignal(float, float, float, float, float, float, float, float, float)
    lost = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.port = QSerialPort(self)
        self.parser = PacketParser()
        self._closing = False
        self.port.readyRead.connect(self._read)
        self.port.errorOccurred.connect(self._on_error)

    def is_open(self) -> bool:
        return self.port.isOpen()

    def open_port(self, name: str) -> tuple[bool, str]:
        if self.port.isOpen():
            self.close_port()
        self.port.setPortName(name)
        self.port.setBaudRate(57600)
        self.port.setDataBits(QSerialPort.DataBits.Data8)
        self.port.setParity(QSerialPort.Parity.NoParity)
        self.port.setStopBits(QSerialPort.StopBits.OneStop)
        self.port.setFlowControl(QSerialPort.FlowControl.NoFlowControl)
        self.parser.reset()
        if not self.port.open(QSerialPort.OpenModeFlag.ReadOnly):
            return False, self.port.errorString() or "Could not open port"
        return True, ""

    def close_port(self) -> None:
        self._closing = True
        if self.port.isOpen():
            self.port.close()
        self._closing = False
        self.parser.reset()

    def _read(self) -> None:
        data = self.port.readAll().data()
        for sample in self.parser.feed(data):
            self.sample.emit(*sample)

    def _on_error(self, err: QSerialPort.SerialPortError) -> None:
        if self._closing:
            return
        benign = (
            QSerialPort.SerialPortError.NoError,
            QSerialPort.SerialPortError.TimeoutError,
        )
        if err in benign:
            return
        message = self.port.errorString() or "Serial port error"
        if self.port.isOpen():
            self._closing = True
            self.port.close()
            self._closing = False
        self.parser.reset()
        self.lost.emit(message)


class SmoothedWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setAutoFillBackground(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)
        self._channels: dict[str, list] = {}

    def _bind(self, name: str, value: float = 0.0, circular: bool = False) -> None:
        self._channels[name] = [value, value, circular]

    def _set(self, name: str, value: float, immediate: bool = False) -> None:
        shown, _target, circular = self._channels[name]
        self._channels[name][1] = value
        if immediate:
            self._channels[name][0] = value
        elif not self._timer.isActive() and abs(value - shown) > 1e-4:
            self._timer.start()
        self.update()

    def _shown(self, name: str) -> float:
        return self._channels[name][0]

    def _target(self, name: str) -> float:
        return self._channels[name][1]

    def _on_tick(self) -> None:
        settled = True
        for channel in self._channels.values():
            nxt, done = ease(channel[0], channel[1], circular=channel[2])
            channel[0] = nxt
            settled = settled and done
        self.update()
        if settled:
            self._timer.stop()


class HorizonWidget(SmoothedWidget):
    def __init__(self) -> None:
        super().__init__()
        self._bind("pitch", 0.0, False)
        self._bind("roll", 0.0, True)
        self.setMinimumSize(280, 260)

    def sizeHint(self) -> QSize:
        return QSize(380, 340)

    def set_attitude(self, pitch: float, roll: float, immediate: bool = False) -> None:
        self._set("pitch", pitch, immediate)
        self._set("roll", (roll + 180.0) % 360.0 - 180.0, immediate)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.fillRect(self.rect(), CARD)

        w, h = self.width(), self.height()
        outer = min(w, h) / 2.0 - 8.0
        if outer < 40:
            return
        cx, cy = w / 2.0, h / 2.0
        inner = outer - 11.0
        pitch = self._shown("pitch")
        roll = self._shown("roll")
        ppd = inner / 52.0

        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), inner, inner)
        painter.save()
        painter.setClipPath(clip, Qt.ClipOperation.ReplaceClip)
        painter.translate(cx, cy)
        painter.rotate(-roll)
        painter.translate(0, pitch * ppd)

        sky = QLinearGradient(0, -900, 0, 0)
        sky.setColorAt(0.0, QColor("#0e2c44"))
        sky.setColorAt(0.62, QColor("#1c5b84"))
        sky.setColorAt(1.0, QColor("#7eb4ce"))
        ground = QLinearGradient(0, 0, 0, 900)
        ground.setColorAt(0.0, QColor("#c4895a"))
        ground.setColorAt(0.45, QColor("#6b4330"))
        ground.setColorAt(1.0, QColor("#24160f"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(sky)
        painter.drawRect(QRectF(-4000, -4000, 8000, 4000))
        painter.setBrush(ground)
        painter.drawRect(QRectF(-4000, 0, 8000, 4000))
        painter.setPen(QPen(QColor(255, 255, 255, 230), 2.0))
        painter.drawLine(QPointF(-3000, 0), QPointF(3000, 0))

        for deg in range(-90, 91, 5):
            if deg == 0:
                continue
            y = -deg * ppd
            major = deg % 10 == 0
            half = inner * (0.30 if major else 0.13)
            painter.setPen(QPen(QColor(255, 255, 255, 225 if major else 130), 1.7 if major else 1.0))
            gap = 16.0
            painter.drawLine(QPointF(-half, y), QPointF(-gap, y))
            painter.drawLine(QPointF(gap, y), QPointF(half, y))
            if major:
                painter.setFont(make_font(8, QFont.Weight.DemiBold))
                painter.drawText(
                    QRectF(-half - 30, y - 9, 26, 18),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    str(abs(deg)),
                )
                painter.drawText(
                    QRectF(half + 4, y - 9, 26, 18),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    str(abs(deg)),
                )
        painter.restore()

        painter.save()
        painter.setClipPath(clip, Qt.ClipOperation.ReplaceClip)
        vignette = QRadialGradient(cx, cy, inner)
        vignette.setColorAt(0.68, QColor(0, 0, 0, 0))
        vignette.setColorAt(1.0, QColor(0, 0, 0, 110))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(vignette)
        painter.drawEllipse(QPointF(cx, cy), inner, inner)
        painter.restore()

        painter.setPen(QPen(QColor(255, 255, 255, 210), 1.4))
        for deg in (-60, -45, -30, -20, -10, 10, 20, 30, 45, 60):
            major = abs(deg) in (30, 60)
            painter.setPen(QPen(QColor(255, 255, 255, 230 if major else 140), 1.8 if major else 1.1))
            painter.drawLine(pt(cx, cy, deg, inner - 7), pt(cx, cy, deg, inner - (20 if major else 14)))
            if major:
                label = pt(cx, cy, deg, inner - 32)
                painter.setFont(make_font(7, QFont.Weight.DemiBold))
                painter.drawText(
                    QRectF(label.x() - 12, label.y() - 8, 24, 16),
                    Qt.AlignmentFlag.AlignCenter,
                    str(abs(deg)),
                )

        self._aircraft(painter, cx, cy, inner)
        paint_bezel(painter, cx, cy, outer, inner)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(AMBER)
        painter.drawPolygon(marker(cx, cy, 0, inner - 5, 11, inward=True))
        painter.setBrush(QColor("#f7f4ee"))
        painter.drawPolygon(marker(cx, cy, roll, inner - 30, 9, inward=False))
        paint_glass(painter, cx, cy, inner - 1)

    def _aircraft(self, painter: QPainter, cx: float, cy: float, inner: float) -> None:
        span = inner * 0.46
        gap = inner * 0.075
        drop = max(6.0, inner * 0.035)
        for color, width in ((QColor(0, 0, 0, 150), 4.6), (AMBER, 2.5)):
            pen = QPen(color, width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(cx - span, cy), QPointF(cx - gap, cy))
            painter.drawLine(QPointF(cx + gap, cy), QPointF(cx + span, cy))
            painter.drawLine(QPointF(cx - span, cy), QPointF(cx - span, cy + drop))
            painter.drawLine(QPointF(cx + span, cy), QPointF(cx + span, cy + drop))
            painter.drawLine(QPointF(cx, cy + 5), QPointF(cx, cy + inner * 0.11))
        painter.setPen(QPen(QColor("#1c1508"), 1))
        painter.setBrush(AMBER)
        painter.drawEllipse(QPointF(cx, cy), 4.5, 4.5)


class CompassWidget(SmoothedWidget):
    _NAMES = {0: "N", 90: "E", 180: "S", 270: "W"}

    def __init__(self) -> None:
        super().__init__()
        self._bind("yaw", 0.0, True)
        self.setMinimumSize(280, 260)

    def sizeHint(self) -> QSize:
        return QSize(380, 340)

    def set_heading(self, yaw: float, immediate: bool = False) -> None:
        self._set("yaw", yaw % 360.0, immediate)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.fillRect(self.rect(), CARD)

        w, h = self.width(), self.height()
        outer = min(w, h) / 2.0 - 8.0
        if outer < 40:
            return
        cx, cy = w / 2.0, h / 2.0
        inner = outer - 11.0
        heading = self._shown("yaw")
        display = self._target("yaw") % 360.0

        face = QRadialGradient(cx, cy - inner * 0.15, inner * 1.15)
        face.setColorAt(0.0, QColor("#1c2533"))
        face.setColorAt(1.0, QColor("#0d1219"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(face)
        painter.drawEllipse(QPointF(cx, cy), inner, inner)

        rose = inner - 16.0
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(-heading)
        for deg in range(0, 360, 5):
            major = deg % 30 == 0
            mid = deg % 10 == 0
            length = 16 if major else 10 if mid else 5
            color = AMBER if deg == 0 else QColor(255, 255, 255, 220 if major else 140)
            painter.setPen(QPen(color, 1.8 if major else 1.1))
            painter.drawLine(pt(0, 0, deg, rose - length), pt(0, 0, deg, rose))
        painter.restore()

        for deg in range(0, 360, 30):
            screen = deg - heading
            pos = pt(cx, cy, screen, rose - 34)
            name = self._NAMES.get(deg)
            if name:
                painter.setFont(make_font(13 if name == "N" else 11, QFont.Weight.Bold))
                painter.setPen(AMBER if name == "N" else TEXT)
                box = 22.0
            else:
                painter.setFont(make_font(8, QFont.Weight.DemiBold))
                painter.setPen(MUTED)
                box = 24.0
            painter.drawText(
                QRectF(pos.x() - box / 2, pos.y() - 9, box, 18),
                Qt.AlignmentFlag.AlignCenter,
                name or str(deg),
            )

        painter.setPen(Qt.PenStyle.NoPen)
        hub = QRadialGradient(cx, cy, inner * 0.36)
        hub.setColorAt(0.0, QColor("#1a222e"))
        hub.setColorAt(1.0, QColor("#121820"))
        painter.setBrush(hub)
        painter.drawEllipse(QPointF(cx, cy), inner * 0.36, inner * 0.36)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#343e50"), 1.2))
        painter.drawEllipse(QPointF(cx, cy), inner * 0.36, inner * 0.36)

        painter.setPen(MUTED)
        painter.setFont(make_font(8, QFont.Weight.DemiBold, 1.5))
        painter.drawText(QRectF(cx - 50, cy - 30, 100, 16), Qt.AlignmentFlag.AlignCenter, "YAW")
        painter.setPen(TEXT)
        painter.setFont(make_font(18, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(cx - 70, cy - 8, 140, 30),
            Qt.AlignmentFlag.AlignCenter,
            f"{display:05.1f}°",
        )

        paint_bezel(painter, cx, cy, outer, inner)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(AMBER)
        painter.drawPolygon(marker(cx, cy, 0, inner - 4, 12, inward=True))
        paint_glass(painter, cx, cy, inner - 1)


class ArcGauge(SmoothedWidget):
    def __init__(
        self,
        title: str,
        unit: str,
        vmin: float,
        vmax: float,
        accent: str,
        decimals: int = 1,
        tick_step: float = 1.0,
    ) -> None:
        super().__init__()
        self.title = title
        self.unit = unit
        self.vmin = vmin
        self.vmax = vmax
        self.accent = QColor(accent)
        self.decimals = decimals
        self.tick_step = tick_step
        self._bind("v", 0.0, False)
        self.setMinimumSize(124, 176)

    def sizeHint(self) -> QSize:
        return QSize(160, 200)

    def set_value(self, value: float, immediate: bool = False) -> None:
        self._set("v", value, immediate)

    def _angle(self, value: float) -> float:
        span = self.vmax - self.vmin
        if span == 0:
            return 0.0
        t = (value - self.vmin) / span
        t = min(1.0, max(0.0, t))
        return -120.0 + t * 240.0

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.fillRect(self.rect(), CARD)

        w, h = float(self.width()), float(self.height())
        title_h = 22.0
        painter.setPen(MUTED)
        painter.setFont(make_font(9, QFont.Weight.DemiBold, 1.3))
        painter.drawText(QRectF(0, 2, w, title_h), Qt.AlignmentFlag.AlignCenter, self.title)

        radius = min(w - 10.0, h - title_h - 6.0) / 2.0
        if radius < 36:
            return
        cx = w / 2.0
        cy = title_h + radius + 2.0

        face = QRadialGradient(cx, cy - radius * 0.25, radius * 1.25)
        face.setColorAt(0.0, QColor("#1c2533"))
        face.setColorAt(1.0, QColor("#10161f"))
        painter.setPen(QPen(QColor("#323c4e"), 1.4))
        painter.setBrush(face)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)

        arc_r = radius * 0.62
        arc = circle_rect(cx, cy, arc_r)
        track = QPen(QColor("#2c3648"), 8.0)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(arc, qt_arc(120), 240 * 16)

        shown = self._shown("v")
        zero = self._angle(0.0)
        ang = self._angle(shown)
        value_pen = QPen(self.accent, 8.0)
        value_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(value_pen)
        painter.drawArc(arc, qt_arc(zero), int(round(-(ang - zero) * 16)))

        painter.setFont(make_font(7.5, QFont.Weight.DemiBold))
        v = self.vmin
        guard = 0
        while v <= self.vmax + abs(self.tick_step) * 0.05 and guard < 40:
            tick_ang = self._angle(v)
            major = abs(v - self.vmin) < 1e-3 or abs(v - self.vmax) < 1e-3 or abs(v) < 1e-3
            painter.setPen(QPen(QColor("#c5ceda" if major else "#7d8b9e"), 1.6 if major else 1.0))
            painter.drawLine(
                pt(cx, cy, tick_ang, arc_r + 8),
                pt(cx, cy, tick_ang, arc_r + (16 if major else 12)),
            )
            if abs(v - self.vmin) < 1e-3 or abs(v - self.vmax) < 1e-3:
                label = pt(cx, cy, tick_ang, min(radius - 18.0, arc_r + 18.0))
                painter.setPen(MUTED)
                text = str(int(round(v)))
                painter.drawText(
                    QRectF(label.x() - 16, label.y() - 7, 32, 14),
                    Qt.AlignmentFlag.AlignCenter,
                    text,
                )
            v += self.tick_step
            guard += 1

        tail = pt(cx, cy, ang + 180.0, radius * 0.13)
        tip = pt(cx, cy, ang, arc_r - 10)
        shadow = QPen(QColor(0, 0, 0, 80), 3.4)
        shadow.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(shadow)
        painter.drawLine(tail + QPointF(1.2, 1.6), tip + QPointF(1.2, 1.6))
        needle = QPen(self.accent, 2.5)
        needle.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(needle)
        painter.drawLine(tail, tip)

        painter.setPen(QPen(self.accent, 1.3))
        painter.setBrush(QColor("#0e131b"))
        painter.drawEllipse(QPointF(cx, cy), radius * 0.055, radius * 0.055)

        target = self._target("v")
        painter.setPen(TEXT)
        painter.setFont(make_font(13, QFont.Weight.DemiBold))
        painter.drawText(
            QRectF(cx - 48, cy + radius * 0.34, 96, 22),
            Qt.AlignmentFlag.AlignCenter,
            f"{target:+.{self.decimals}f}",
        )
        painter.setPen(MUTED)
        painter.setFont(make_font(8))
        painter.drawText(
            QRectF(cx - 40, cy + radius * 0.34 + 18, 80, 16),
            Qt.AlignmentFlag.AlignCenter,
            self.unit,
        )


class Dashboard(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("IMU Instruments")
        self.resize(1180, 800)
        self.setMinimumSize(1080, 700)
        self.link = SerialLink(self)
        self.link.sample.connect(self._on_sample)
        self.link.lost.connect(self._on_lost)

        self._packets = 0
        self._receiving = False
        self._rate_t = time.monotonic()
        self._preview_t0 = time.monotonic()

        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(33)
        self._preview_timer.timeout.connect(self._preview_tick)
        self._watch = QTimer(self)
        self._watch.setSingleShot(True)
        self._watch.timeout.connect(self._on_stale)
        self._rate_timer = QTimer(self)
        self._rate_timer.setInterval(500)
        self._rate_timer.timeout.connect(self._update_rate)
        self._rate_timer.start()

        self._build()
        self._reload_ports()
        self.show_sample(0, 0, 0, 0, 0, 1, 0, 0, 0, immediate=True)
        self.set_status("Disconnected", "idle")

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 16, 20, 18)
        outer.setSpacing(14)
        outer.addLayout(self._header())

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addLayout(self._left_column(), 1)
        body.addLayout(self._right_column(), 1)
        outer.addLayout(body, 1)
        self.setStyleSheet(STYLESHEET)

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        word = QLabel("IMU INSTRUMENTS")
        word.setObjectName("wordmark")
        sub = QLabel("MPU9250    ·    57600 baud")
        sub.setObjectName("subtitle")
        titles.addWidget(word)
        titles.addWidget(sub)
        row.addLayout(titles)
        row.addStretch(1)

        self.ports = QComboBox()
        self.ports.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ports.setMinimumWidth(150)
        self.ports.setMaximumWidth(240)
        self.ports.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.ports.currentTextChanged.connect(self.ports.setToolTip)
        row.addWidget(self.ports)

        self.refresh_btn = self._button("Refresh", "ghost", self._reload_ports, "Scan for serial ports")
        self.preview_btn = self._button("Preview", "ghost", None, "Animate the gauges without a board")
        self.preview_btn.setCheckable(True)
        self.preview_btn.toggled.connect(self._on_preview)
        self.connect_btn = self._button("Connect", "primary", self._on_connect, "Open the selected port at 57600 baud")
        row.addWidget(self.refresh_btn)
        row.addWidget(self.preview_btn)
        row.addWidget(self.connect_btn)

        self.status = QLabel()
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.status)
        self.hz = QLabel("0 Hz")
        self.hz.setObjectName("hz")
        self.hz.setFixedWidth(58)
        self.hz.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.hz)
        return row

    def _button(self, text: str, name: str, slot, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(tip)
        if slot:
            button.clicked.connect(slot)
        return button

    def _left_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(14)
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(4)
        layout.addWidget(self._section("ATTITUDE"))
        self.horizon = HorizonWidget()
        layout.addWidget(self.horizon, 1)
        layout.addLayout(self._readouts())
        col.addWidget(card, 3)

        accel = self._card()
        al = QVBoxLayout(accel)
        al.setContentsMargins(12, 12, 12, 8)
        al.setSpacing(0)
        al.addWidget(self._section("ACCELERATION"))
        row = QHBoxLayout()
        row.setSpacing(2)
        self.ax = ArcGauge("AX", "g", -2, 2, "#e4b15a", decimals=2, tick_step=1)
        self.ay = ArcGauge("AY", "g", -2, 2, "#6fbfb8", decimals=2, tick_step=1)
        self.az = ArcGauge("AZ", "g", -2, 2, "#9eb6e0", decimals=2, tick_step=1)
        row.addWidget(self.ax)
        row.addWidget(self.ay)
        row.addWidget(self.az)
        al.addLayout(row, 1)
        col.addWidget(accel, 2)
        return col

    def _right_column(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(14)
        card = self._card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(4)
        layout.addWidget(self._section("HEADING"))
        self.compass = CompassWidget()
        layout.addWidget(self.compass, 1)
        note = QLabel("Yaw is integrated from the Z gyro and will drift")
        note.setObjectName("note")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(note)
        col.addWidget(card, 3)

        gyro = self._card()
        gl = QVBoxLayout(gyro)
        gl.setContentsMargins(12, 12, 12, 8)
        gl.setSpacing(0)
        gl.addWidget(self._section("ANGULAR RATE"))
        row = QHBoxLayout()
        row.setSpacing(2)
        self.gx = ArcGauge("GX", "°/s", -250, 250, "#e4b15a", decimals=1, tick_step=50)
        self.gy = ArcGauge("GY", "°/s", -250, 250, "#6fbfb8", decimals=1, tick_step=50)
        self.gz = ArcGauge("GZ", "°/s", -250, 250, "#9eb6e0", decimals=1, tick_step=50)
        row.addWidget(self.gx)
        row.addWidget(self.gy)
        row.addWidget(self.gz)
        gl.addLayout(row, 1)
        col.addWidget(gyro, 2)
        return col

    def _card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setFrameShape(QFrame.Shape.NoFrame)
        frame.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        return frame

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        return label

    def _readouts(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(12, 0, 12, 0)
        self.pitch_value = self._readout(row, "PITCH")
        self.roll_value = self._readout(row, "ROLL")
        return row

    def _readout(self, row: QHBoxLayout, caption: str) -> QLabel:
        box = QVBoxLayout()
        box.setSpacing(0)
        cap = QLabel(caption)
        cap.setObjectName("caption")
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value = QLabel("+0.0°")
        value.setObjectName("value")
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(cap)
        box.addWidget(value)
        row.addLayout(box)
        return value

    def _style_button(self, button: QPushButton, name: str) -> None:
        button.setObjectName(name)
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def set_status(self, text: str, kind: str) -> None:
        colors = {
            "live": ("#7dcea0", "#14241c"),
            "wait": ("#e4b15a", "#282114"),
            "idle": ("#8e9aab", "#1b2230"),
            "preview": ("#8fd4ce", "#142624"),
            "error": ("#e08b90", "#2a181c"),
        }
        tips = {
            "wait": "Calibration text is ignored. Gauges move once binary packets start.",
            "live": "Receiving IMU packets.",
            "idle": "Choose the Arduino port and connect. Close Serial Monitor first.",
            "preview": "Synthetic motion, not live sensor data.",
            "error": text,
        }
        fg, bg = colors[kind]
        self.status.setToolTip(tips[kind])
        shown = text if len(text) <= 28 else text[:27] + "…"
        self.status.setText("●   " + shown)
        self.status.setStyleSheet(
            "QLabel {"
            f"color: {fg}; background: {bg};"
            "border-radius: 11px; padding: 5px 12px; font-weight: 650; font-size: 12px;"
            "}"
        )

    def show_sample(
        self,
        pitch: float,
        roll: float,
        yaw: float,
        ax: float,
        ay: float,
        az: float,
        gx: float,
        gy: float,
        gz: float,
        immediate: bool = False,
    ) -> None:
        self.horizon.set_attitude(pitch, roll, immediate)
        self.compass.set_heading(yaw, immediate)
        self.ax.set_value(ax, immediate)
        self.ay.set_value(ay, immediate)
        self.az.set_value(az, immediate)
        self.gx.set_value(gx, immediate)
        self.gy.set_value(gy, immediate)
        self.gz.set_value(gz, immediate)
        self.pitch_value.setText(f"{pitch:+.1f}°")
        self.roll_value.setText(f"{roll:+.1f}°")

    def _reload_ports(self) -> None:
        selected = self.ports.currentData()
        self.ports.blockSignals(True)
        self.ports.clear()
        found = sorted(QSerialPortInfo.availablePorts(), key=lambda info: info.portName())
        if not found:
            self.ports.addItem("No serial ports found", None)
            self.connect_btn.setEnabled(False)
        else:
            for info in found:
                desc = info.description().strip()
                label = f"{info.portName()}    {desc}" if desc else info.portName()
                self.ports.addItem(label, info.portName())
            if not self.link.is_open():
                self.connect_btn.setEnabled(True)
            index = self.ports.findData(selected)
            if index >= 0:
                self.ports.setCurrentIndex(index)
        self.ports.blockSignals(False)
        self.ports.setToolTip(self.ports.currentText())

    def _on_connect(self) -> None:
        if self.link.is_open():
            self.link.close_port()
            self._receiving = False
            self._set_link_ui(False)
            self.set_status("Disconnected", "idle")
            self.hz.setText("0 Hz")
            return
        name = self.ports.currentData()
        if not name:
            return
        if self.preview_btn.isChecked():
            self.preview_btn.setChecked(False)
        ok, message = self.link.open_port(name)
        if not ok:
            self.set_status("Could not open port", "error")
            QMessageBox.warning(
                self,
                "Serial port",
                f"Could not open {name}.\n\n{message}\n\n"
                "Close the Arduino Serial Monitor if it is using this port.",
            )
            return
        self._receiving = False
        self._set_link_ui(True)
        self.set_status("Waiting for packets", "wait")
        self.hz.setText("0 Hz")

    def _set_link_ui(self, connected: bool) -> None:
        self.connect_btn.setText("Disconnect" if connected else "Connect")
        self._style_button(self.connect_btn, "ghost" if connected else "primary")
        self.ports.setEnabled(not connected)
        self.refresh_btn.setEnabled(not connected)
        self.preview_btn.setEnabled(not connected)
        if not connected:
            self.connect_btn.setEnabled(self.ports.currentData() is not None)

    def _on_preview(self, enabled: bool) -> None:
        if enabled and self.link.is_open():
            self.preview_btn.setChecked(False)
            return
        if enabled:
            self._preview_t0 = time.monotonic()
            self._preview_timer.start()
            self.set_status("Preview", "preview")
            self.hz.setText("sim")
            return
        self._preview_timer.stop()
        if not self.link.is_open():
            self.set_status("Disconnected", "idle")
            self.hz.setText("0 Hz")
            self.show_sample(0, 0, 0, 0, 0, 1, 0, 0, 0)

    def _preview_tick(self) -> None:
        t = time.monotonic() - self._preview_t0
        self.show_sample(
            10.0 * math.sin(t * 0.55) + 4.0 * math.sin(t * 0.17),
            16.0 * math.sin(t * 0.37),
            (t * 14.0) % 360.0,
            0.28 * math.sin(t * 0.80),
            0.18 * math.sin(t * 0.63 + 0.8),
            0.98 + 0.06 * math.sin(t * 1.10),
            35.0 * math.sin(t * 0.70),
            22.0 * math.sin(t * 0.90 + 0.5),
            18.0 * math.sin(t * 0.45 + 1.1),
        )

    def _on_sample(self, pitch, roll, yaw, ax, ay, az, gx, gy, gz) -> None:
        self._packets += 1
        if not self._receiving:
            self._receiving = True
            name = self.link.port.portName()
            self.set_status(f"Live    {name}", "live")
        self._watch.start(1000)
        self.show_sample(pitch, roll, yaw, ax, ay, az, gx, gy, gz)

    def _on_stale(self) -> None:
        if self.preview_btn.isChecked() or not self.link.is_open():
            return
        self._receiving = False
        name = self.link.port.portName()
        self.set_status(f"Waiting    {name}", "wait")

    def _on_lost(self, message: str) -> None:
        self._receiving = False
        self._set_link_ui(False)
        self.hz.setText("0 Hz")
        self.set_status(message or "Serial port lost", "error")

    def _update_rate(self) -> None:
        now = time.monotonic()
        dt = max(now - self._rate_t, 1e-3)
        rate = self._packets / dt
        self._packets = 0
        self._rate_t = now
        if self.preview_btn.isChecked():
            self.hz.setText("sim")
        elif self._receiving:
            self.hz.setText(f"{rate:.0f} Hz")
        else:
            self.hz.setText("0 Hz")

    def closeEvent(self, event) -> None:
        self._preview_timer.stop()
        self.link.close_port()
        super().closeEvent(event)


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, BG)
    palette.setColor(QPalette.ColorRole.WindowText, TEXT)
    palette.setColor(QPalette.ColorRole.Base, CARD)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1b2230"))
    palette.setColor(QPalette.ColorRole.Text, TEXT)
    palette.setColor(QPalette.ColorRole.Button, QColor("#1b2230"))
    palette.setColor(QPalette.ColorRole.ButtonText, TEXT)
    palette.setColor(QPalette.ColorRole.Highlight, AMBER)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#1c1508"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#1b2230"))
    palette.setColor(QPalette.ColorRole.ToolTipText, TEXT)
    palette.setColor(QPalette.ColorRole.PlaceholderText, MUTED)
    app.setPalette(palette)
    app.setFont(QFont("Segoe UI", 10))


def main() -> None:
    app = QApplication(sys.argv)
    apply_theme(app)
    app.setApplicationName("IMU Instruments")
    window = Dashboard()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
