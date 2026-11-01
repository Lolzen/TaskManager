"""Look and feel helpers of the Windows 8 layout."""

from .. import theme
from ..qt import QtCore, QtGui, QtWidgets, Qt
from ..widgets.tree import SortItem, blend

STYLE = """
QMainWindow#win8, QWidget#win8page { background: $base_bg; }
QTabWidget::pane { border: none; border-top: 1px solid $border; background: $base_bg; top: -1px; }
QTabWidget::tab-bar { left: 2px; }
QTabBar::tab {
    background: $base_bg; color: $text; border: 1px solid transparent; border-bottom: none;
    padding: 3px 9px 4px 9px; margin-right: 0px;
}
QTabBar::tab:hover:!selected { background: $tab_hover; border-color: $tab_hover; }
QTabBar::tab:selected { border-color: $border; background: $base_bg; }
QTreeWidget { border: none; background: $base_bg; color: $text; selection-background-color: $selected_bg; selection-color: $selected_text; outline: 0; }
QTreeWidget::item { padding: 1px 0px; border: none; }
QTreeWidget::item:hover { background: $hover_bg; }
QTreeWidget::item:selected { background: $selected_bg; color: $selected_text; }
QHeaderView { background: $base_bg; }
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $btn_top, stop:1 $btn_bottom);
    border: 1px solid $btn_border; padding: 3px 16px; min-height: 16px; color: $text;
}
QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $btn_hover_top, stop:1 $btn_hover_bottom); border-color: $btn_hover_border; }
QPushButton:pressed { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 $btn_pressed_top, stop:1 $btn_pressed_bottom); border-color: $btn_pressed_border; }
QPushButton:disabled { background: $btn_disabled_bg; border-color: $btn_disabled_border; color: $disabled_text; }
QMenuBar { background: $base_bg; color: $text; }
QMenuBar::item:selected { background: $hover_bg; }
QLabel#win8link, QToolButton#win8link { color: $link; }
QToolButton#win8link { border: none; background: transparent; padding: 2px; }
QToolButton#win8link:hover { color: $link_hover; text-decoration: underline; }
QWidget#bottombar { background: $base_bg; border-top: 1px solid $separator; }
QScrollArea { border: none; background: $base_bg; }
QListWidget#compact { border: none; background: $base_bg; color: $text; outline: 0; }
QListWidget#compact::item { padding: 3px 4px; }
QListWidget#compact::item:hover { background: $hover_bg; }
QListWidget#compact::item:selected { background: $selected_bg; color: $selected_text; }
"""

def heat_color(t):
    """Yellow-to-orange shading Windows 8 uses for busy cells and headers."""
    stops = theme.heat_stops()
    t = max(0.0, min(1.0, t))
    segment = min(len(stops) - 2, int(t * (len(stops) - 1)))
    local = t * (len(stops) - 1) - segment
    return blend(stops[segment], stops[segment + 1], local)


HEAT_ROLE = Qt.ItemDataRole.UserRole + 3


class HeatDelegate(QtWidgets.QStyledItemDelegate):
    """Paints the heat-map shading under a cell.

    Item background brushes are ignored once a style sheet styles
    ``::item``, so the shade is stored in ``HEAT_ROLE`` and painted here.
    """

    def paint(self, painter, option, index):
        color = index.data(HEAT_ROLE)
        if color is not None:
            painter.fillRect(option.rect, color)
        super().paint(painter, option, index)


def set_heat(item, column, t):
    color = heat_color(t)
    if item.data(column, HEAT_ROLE) != color:
        item.setData(column, HEAT_ROLE, color)


class MetricHeader(QtWidgets.QHeaderView):
    """Two line header (``12%`` above ``CPU``) with heat shading and the
    small centred sort caret of the Windows 8 Task Manager."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.metrics = {}  # logical index -> (value text, heat 0..1 or None)
        self.right_aligned = set()
        self.setSectionsClickable(True)
        self.setSectionsMovable(True)
        self.setHighlightSections(False)
        self.setStretchLastSection(True)
        self.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setHeight(44)
        return hint

    def set_metric(self, index, text, heat):
        if self.metrics.get(index) != (text, heat):
            self.metrics[index] = (text, heat)
            self.viewport().update()

    def paintSection(self, painter, rect, index):
        if not rect.isValid():
            return
        painter.save()
        metric = self.metrics.get(index)
        background = theme.qcolor("base_bg")
        if metric is not None and metric[1] is not None and metric[1] > 0.5:
            background = heat_color((metric[1] - 0.5) * 2)
        painter.fillRect(rect, background)
        painter.setPen(theme.qcolor("separator"))
        painter.drawLine(rect.topRight(), rect.bottomRight())
        painter.drawLine(rect.bottomLeft(), rect.bottomRight())

        label = str(self.model().headerData(index, Qt.Orientation.Horizontal) or "")
        align = Qt.AlignmentFlag.AlignRight if index in self.right_aligned else Qt.AlignmentFlag.AlignLeft
        inner = rect.adjusted(6, 3, -6, -4)
        font = QtGui.QFont(self.font())
        painter.setFont(font)
        painter.setPen(theme.qcolor("header_text"))
        painter.drawText(inner, int(align | Qt.AlignmentFlag.AlignBottom),
                         painter.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, inner.width()))
        if metric is not None and metric[0]:
            big = QtGui.QFont(font)
            big.setPointSizeF(font.pointSizeF() * 1.45)
            painter.setFont(big)
            painter.setPen(theme.qcolor("text"))
            painter.drawText(inner.adjusted(0, 6, 0, 0), int(align | Qt.AlignmentFlag.AlignTop), metric[0])

        if self.isSortIndicatorShown() and self.sortIndicatorSection() == index:
            cx, top = rect.center().x(), rect.top() + 2
            painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QtGui.QPen(theme.qcolor("caret"), 1.2))
            if self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder:
                pts = [QtCore.QPointF(cx - 4, top + 4), QtCore.QPointF(cx, top), QtCore.QPointF(cx + 4, top + 4)]
            else:
                pts = [QtCore.QPointF(cx - 4, top), QtCore.QPointF(cx, top + 4), QtCore.QPointF(cx + 4, top)]
            painter.drawPolyline(QtGui.QPolygonF(pts))
        painter.restore()


def install_header(tree, right_aligned=()):
    header = MetricHeader(tree)
    tree.setHeader(header)
    # re-arm sorting so the view listens to the new header's sort indicator
    tree.setSortingEnabled(False)
    tree.setSortingEnabled(True)
    header.right_aligned = set(right_aligned)
    tree.setItemDelegate(HeatDelegate(tree))
    header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    return header


def column_menu(tree, columns, always=("Name",)):
    """Header right-click menu that shows/hides columns, like Windows 8."""
    header = tree.header()

    def show(pos):
        menu = QtWidgets.QMenu(tree)
        for idx, title in enumerate(columns):
            act = menu.addAction(title)
            act.setCheckable(True)
            act.setChecked(not header.isSectionHidden(idx))
            act.setEnabled(title not in always)
            act.toggled.connect(lambda checked, i=idx: header.setSectionHidden(i, not checked))
        menu.exec(header.mapToGlobal(pos))

    header.customContextMenuRequested.connect(show)


class GroupItem(SortItem):
    """``Apps (3)`` style header row that keeps its place while sorting."""

    def __init__(self, rank, title):
        super().__init__()
        self.rank = rank
        self.title = title
        font = QtGui.QFont()
        font.setBold(True)
        self.setFont(0, font)
        self.setForeground(0, QtGui.QBrush(theme.qcolor("group_text")))
        self.setFirstColumnSpanned(True)
        self.setFlags(Qt.ItemFlag.ItemIsEnabled)

    def set_count(self, count):
        text = "{} ({})".format(self.title, count)
        if self.text(0) != text:
            self.setText(0, text)


class LinkButton(QtWidgets.QToolButton):
    def __init__(self, text, arrow=None, parent=None):
        super().__init__(parent)
        self.setObjectName("win8link")
        self.setText(text)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if arrow is not None:
            self.setArrowType(arrow)
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)


def bottom_bar(left_widgets, right_widgets):
    bar = QtWidgets.QWidget()
    bar.setObjectName("bottombar")
    bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    lay = QtWidgets.QHBoxLayout(bar)
    lay.setContentsMargins(8, 6, 10, 8)
    for widget in left_widgets:
        lay.addWidget(widget)
    lay.addStretch(1)
    for widget in right_widgets:
        lay.addWidget(widget)
    return bar


_icon_cache = {}


def icon_for(name, fallback):
    key = (name, fallback)
    if key not in _icon_cache:
        icon = QtGui.QIcon.fromTheme(name) if name else QtGui.QIcon()
        if icon.isNull():
            icon = QtWidgets.QApplication.style().standardIcon(fallback)
        _icon_cache[key] = icon
    return _icon_cache[key]


APP_ICON = QtWidgets.QStyle.StandardPixmap.SP_DesktopIcon
PROC_ICON = QtWidgets.QStyle.StandardPixmap.SP_FileIcon
SYS_ICON = QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon
USER_ICON = QtWidgets.QStyle.StandardPixmap.SP_DirHomeIcon
