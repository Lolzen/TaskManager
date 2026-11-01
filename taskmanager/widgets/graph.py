"""Custom painted graphs used by both layouts.

``HistoryGraph`` covers the black/green scrolling grids of Windows 7 as well as
the flat, tinted graphs of Windows 8; ``LedMeter`` is the Windows 7 usage
gauge; ``CompositionBar`` is the Windows 8 *Memory composition* bar.
"""

from collections import deque
from dataclasses import dataclass, field

from .. import theme
from ..qt import QtCore, QtGui, QtWidgets, Qt


def qc(value, alpha=None):
    color = QtGui.QColor(value)
    if alpha is not None:
        color.setAlpha(alpha)
    return color


@dataclass
class GraphStyle:
    background: str = "#000000"
    grid: str = "#008040"
    border: str = ""
    lines: list = field(default_factory=lambda: ["#00FF00"])
    fills: list = field(default_factory=lambda: [None])
    dashed: list = field(default_factory=lambda: [False])
    grid_px: int = 12  # square cells (Windows 7); 0 = use rows/cols
    rows: int = 10
    cols: int = 20
    step_px: float = 0  # 0 = stretch ``points`` over the width
    line_width: float = 1.0


WIN7_STYLE = GraphStyle()
WIN7_KERNEL_STYLE = GraphStyle(lines=["#00FF00", "#FF0000"], fills=[None, None], dashed=[False, False])


def win8_style(line, fill, grid, dashed_second=False):
    return GraphStyle(
        background=theme.c("graph_bg"), grid=grid, border=line,
        lines=[line, line], fills=[fill, None], dashed=[False, dashed_second],
        grid_px=0, rows=10, cols=20, line_width=1.0,
    )



def win8_graph(kind, dashed_second=False):
    """Style of a Windows 8/10 performance graph in the current colour scheme."""
    return win8_style(*theme.graph_colors(kind), dashed_second=dashed_second)


class HistoryGraph(QtWidgets.QWidget):
    def __init__(self, style=None, points=60, series=1, maximum=100.0, parent=None):
        super().__init__(parent)
        self.gstyle = style or WIN7_STYLE
        self.points = points
        self.maximum = maximum
        self.autoscale = False
        self.data = [deque([None] * points, maxlen=points) for _ in range(series)]
        self.offset = 0  # grid scroll position, in samples
        self.setMinimumSize(40, 30)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)

    def set_series_count(self, count):
        while len(self.data) < count:
            self.data.append(deque([None] * self.points, maxlen=self.points))
        del self.data[count:]

    def push(self, *values):
        for idx, series in enumerate(self.data):
            series.append(values[idx] if idx < len(values) else None)
        self.offset += 1
        if self.autoscale:
            peak = max((v for s in self.data for v in s if v is not None), default=0.0)
            self.maximum = nice_ceiling(peak)
        self.update()

    def clear(self):
        for series in self.data:
            series.extend([None] * self.points)
        self.update()

    def _step(self, width):
        if self.gstyle.step_px:
            return self.gstyle.step_px
        return width / max(1, self.points - 1)

    def paintEvent(self, _event):
        st = self.gstyle
        p = QtGui.QPainter(self)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        w, h = rect.width(), rect.height()
        p.fillRect(self.rect(), qc(st.background))
        step = self._step(w)

        # grid ------------------------------------------------------------
        p.setPen(QtGui.QPen(qc(st.grid), 1))
        if st.grid_px:
            cell_x = cell_y = st.grid_px
        else:
            cell_x, cell_y = w / st.cols, h / st.rows
        shift = (self.offset * step) % cell_x
        x = rect.right() - shift
        while x > rect.left():
            p.drawLine(QtCore.QPointF(x, rect.top()), QtCore.QPointF(x, rect.bottom()))
            x -= cell_x
        y = rect.bottom() - cell_y if st.grid_px else rect.top() + cell_y
        if st.grid_px:
            while y > rect.top():
                p.drawLine(QtCore.QPointF(rect.left(), y), QtCore.QPointF(rect.right(), y))
                y -= cell_y
        else:
            for row in range(1, st.rows):
                yy = rect.top() + row * cell_y
                p.drawLine(QtCore.QPointF(rect.left(), yy), QtCore.QPointF(rect.right(), yy))

        # series ----------------------------------------------------------
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        maximum = self.maximum or 1.0
        for idx, series in enumerate(self.data):
            pts = []
            n = len(series)
            for i, value in enumerate(series):
                if value is None:
                    continue
                xx = rect.right() - (n - 1 - i) * step
                if xx < rect.left() - step:
                    continue
                yy = rect.bottom() - min(1.0, max(0.0, value / maximum)) * h
                pts.append(QtCore.QPointF(max(rect.left(), xx), yy))
            if len(pts) < 2:
                continue
            fill = st.fills[idx] if idx < len(st.fills) else None
            if fill:
                poly = QtGui.QPolygonF(pts + [QtCore.QPointF(pts[-1].x(), rect.bottom()),
                                              QtCore.QPointF(pts[0].x(), rect.bottom())])
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qc(fill))
                p.drawPolygon(poly)
            pen = QtGui.QPen(qc(st.lines[idx % len(st.lines)]), st.line_width)
            if idx < len(st.dashed) and st.dashed[idx]:
                pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline(QtGui.QPolygonF(pts))

        if st.border:
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, False)
            p.setPen(QtGui.QPen(qc(st.border), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()


def nice_ceiling(value):
    """Round a peak up to a 1/2/5 x 10^n boundary for auto-scaled graphs."""
    if value <= 0:
        return 1.0
    magnitude = 1.0
    while magnitude * 10 <= value:
        magnitude *= 10
    while magnitude > value:
        magnitude /= 10
    for mult in (1, 2, 5, 10):
        if magnitude * mult >= value:
            return magnitude * mult
    return magnitude * 10  # pragma: no cover


class LedMeter(QtWidgets.QWidget):
    """Windows 7 *CPU Usage* / *Memory* gauge: two columns of LED segments."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0.0  # 0..100
        self.kernel = 0.0
        self.text = "0 %"
        self.show_kernel = False
        self.setMinimumSize(70, 90)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Expanding)
        self.setFixedWidth(78)

    def set_value(self, value, text, kernel=0.0):
        self.value, self.text, self.kernel = value, text, kernel
        self.update()

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), Qt.GlobalColor.black)
        font = QtGui.QFont(self.font())
        font.setPixelSize(11)
        p.setFont(font)
        text_h = 18
        p.setPen(qc("#00FF00"))
        p.drawText(QtCore.QRect(0, self.height() - text_h - 2, self.width(), text_h),
                   Qt.AlignmentFlag.AlignCenter, self.text)

        top, bottom = 8, self.height() - text_h - 6
        bar_w = 20
        gap = 2
        left = (self.width() - (2 * bar_w + gap)) // 2
        seg_h, seg_gap = 2, 1
        count = max(1, (bottom - top) // (seg_h + seg_gap))
        lit = int(round(count * min(100.0, self.value) / 100.0))
        kernel_lit = int(round(count * min(100.0, self.kernel) / 100.0)) if self.show_kernel else 0
        if self.value > 0 and lit == 0:
            lit = 1
        for i in range(count):
            y = bottom - (i + 1) * (seg_h + seg_gap)
            if i < kernel_lit:
                color = qc("#FF0000")
            elif i < lit:
                color = qc("#00FF00")
            else:
                color = qc("#008040")
            for col in range(2):
                x = left + col * (bar_w + gap)
                p.fillRect(x, y, bar_w, seg_h, color)
        p.end()


class CompositionBar(QtWidgets.QWidget):
    """Windows 8 *Memory composition*: In use | Modified | Standby | Free."""

    def __init__(self, color=None, parent=None):
        super().__init__(parent)
        self.color = qc(color or theme.graph_colors("mem")[0])
        self.parts = [0, 0, 0, 0]
        self.total = 1
        self.setFixedHeight(46)
        self.setMouseTracking(True)

    def set_parts(self, in_use, modified, standby, free, total):
        self.parts = [in_use, modified, standby, free]
        self.total = max(1, total)
        self.setToolTip(
            "In use: {:.1f} GB\nModified: {:.0f} MB\nStandby: {:.1f} GB\nFree: {:.1f} GB".format(
                in_use / 2 ** 30, modified / 2 ** 20, standby / 2 ** 30, free / 2 ** 30))
        self.update()

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        rect = self.rect().adjusted(0, 0, -1, -1)
        background = theme.qcolor("graph_bg")
        p.fillRect(rect, background)
        fills = [qc(self.color, 110), qc(self.color, 60), qc(self.color, 25), background]
        x = float(rect.left())
        for idx, part in enumerate(self.parts):
            width = rect.width() * part / self.total
            if idx == len(self.parts) - 1:
                width = rect.right() - x
            area = QtCore.QRectF(x, rect.top(), max(0.0, width), rect.height())
            p.fillRect(area, fills[idx])
            if idx < len(self.parts) - 1 and width > 0:
                p.setPen(QtGui.QPen(self.color, 1))
                p.drawLine(QtCore.QPointF(x + width, rect.top()), QtCore.QPointF(x + width, rect.bottom()))
            x += width
        p.setPen(QtGui.QPen(self.color, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(rect)
        p.end()
