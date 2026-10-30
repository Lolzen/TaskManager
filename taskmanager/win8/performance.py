"""Windows 8 *Performance* tab: sidebar of mini graphs and detail pages."""

from ..backend import actions, sysinfo
from ..backend.formatting import (fmt_bits, fmt_cache, fmt_freq, fmt_gb, fmt_link_speed, fmt_rate,
                                  fmt_uptime)
from ..qt import QtGui, QtWidgets, Qt, Signal
from ..widgets.dialogs import show_error
from ..widgets.graph import (WIN8_CPU, WIN8_DISK, WIN8_MEM, WIN8_NET, CompositionBar, HistoryGraph,
                             nice_ceiling, win8_style)
from .common import LinkButton, bottom_bar

GRAY = "#707070"
POINTS = 60


def _label(text="", size=None, color=None, light=False, bold=False):
    label = QtWidgets.QLabel(text)
    font = label.font()
    if size:
        font.setPointSizeF(size)
    if light:
        font.setWeight(QtGui.QFont.Weight.Light)
    if bold:
        font.setBold(True)
    label.setFont(font)
    if color:
        label.setStyleSheet("color: {};".format(color))
    return label


def _mini_style(colors):
    style = win8_style(*colors)
    style.rows, style.cols = 1, 1  # no inner grid lines on thumbnails
    style.grid = colors[1]
    return style


class SideItem(QtWidgets.QFrame):
    clicked = Signal(str)
    double_clicked = Signal()

    def __init__(self, key, title, colors, series=1, parent=None):
        super().__init__(parent)
        self.key = key
        self.selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)
        self.graph = HistoryGraph(_mini_style(colors), POINTS, series=series)
        self.graph.setFixedSize(68, 46)
        self.graph.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.graph)
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(0)
        self.title = _label(title, 13)
        self.sub = _label("", 9, "#000000")
        self.sub2 = _label("", 9, "#000000")
        self.sub2.hide()
        text.addStretch(1)
        text.addWidget(self.title)
        text.addWidget(self.sub)
        text.addWidget(self.sub2)
        text.addStretch(1)
        layout.addLayout(text, 1)
        self._apply()

    def set_selected(self, selected):
        self.selected = selected
        self._apply()

    def _apply(self):
        if self.selected:
            self.setStyleSheet("SideItem { background: #CCE8FF; border: 1px solid #CCE8FF; }")
        else:
            self.setStyleSheet("SideItem { background: transparent; border: 1px solid transparent; }"
                               "SideItem:hover { background: #E5F3FF; border: 1px solid #E5F3FF; }")

    def set_text(self, line1, line2=None):
        self.sub.setText(line1)
        self.sub2.setVisible(bool(line2))
        if line2:
            self.sub2.setText(line2)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class StatBlock(QtWidgets.QWidget):
    """The two stat areas under each graph: big values and a key/value list."""

    def __init__(self, big_rows, small, parent=None):
        super().__init__(parent)
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(28)
        big = QtWidgets.QVBoxLayout()
        big.setSpacing(6)
        self.values = {}
        for row in big_rows:
            line = QtWidgets.QHBoxLayout()
            line.setSpacing(22)
            for name in row:
                cell = QtWidgets.QVBoxLayout()
                cell.setSpacing(0)
                cell.addWidget(_label(name, 9, GRAY))
                value = _label("", 14)
                cell.addWidget(value)
                self.values[name] = value
                line.addLayout(cell)
            line.addStretch(1)
            big.addLayout(line)
        big.addStretch(1)
        outer.addLayout(big)
        grid = QtWidgets.QGridLayout()
        grid.setVerticalSpacing(1)
        grid.setHorizontalSpacing(16)
        for idx, name in enumerate(small):
            grid.addWidget(_label(name + ":", 9, GRAY), idx, 0)
            value = _label("", 9)
            grid.addWidget(value, idx, 1)
            self.values[name] = value
        grid.setRowStretch(len(small), 1)
        outer.addLayout(grid)
        outer.addStretch(1)

    def set(self, name, text):
        label = self.values[name]
        if label.text() != text:
            label.setText(text)

    def text(self):
        return "\n".join("    {}: {}".format(k, v.text()) for k, v in self.values.items())


class GraphFrame(QtWidgets.QWidget):
    """``% Utilization`` / ``100%`` labels around a graph."""

    def __init__(self, left, right, graph, footer=True, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        top = QtWidgets.QHBoxLayout()
        self.left = _label(left, 9, GRAY)
        self.right = _label(right, 9, GRAY)
        top.addWidget(self.left)
        top.addStretch(1)
        top.addWidget(self.right)
        layout.addLayout(top)
        self.graph = graph
        layout.addWidget(graph, 1)
        if footer:
            bottom = QtWidgets.QHBoxLayout()
            bottom.addWidget(_label("60 seconds", 9, GRAY))
            bottom.addStretch(1)
            bottom.addWidget(_label("0", 9, GRAY))
            layout.addLayout(bottom)


class DetailPage(QtWidgets.QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("win8page")
        self.layout_ = QtWidgets.QVBoxLayout(self)
        self.layout_.setContentsMargins(14, 8, 14, 8)
        self.layout_.setSpacing(4)
        head = QtWidgets.QHBoxLayout()
        self.title = _label(title, 20, light=True)
        self.subtitle = _label("", 11)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.subtitle, 0, Qt.AlignmentFlag.AlignBottom)
        self.layout_.addLayout(head)
        self.stats = None
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def extend_menu(self, menu):
        pass

    def _menu(self, pos):
        menu = QtWidgets.QMenu(self)
        self.extend_menu(menu)
        menu.addAction("Copy", self.copy)
        menu.exec(self.mapToGlobal(pos))

    def copy(self):
        text = "{}\n    {}\n".format(self.title.text(), self.subtitle.text())
        if self.stats is not None:
            text += "\n" + self.stats.text()
        QtWidgets.QApplication.clipboard().setText(text)


class CpuPage(DetailPage):
    def __init__(self, info, parent=None):
        super().__init__("CPU", parent)
        self.info = info
        self.subtitle.setText(info.model)
        self.show_kernel = False
        self.logical = False
        self.style_ = win8_style(*WIN8_CPU, dashed_second=False)
        self.style_.lines = [WIN8_CPU[0], "#5DA6D6"]
        self.style_.fills = [WIN8_CPU[1], "#D7E7F3"]
        self.overall = HistoryGraph(self.style_, POINTS, series=2)
        self.grid_holder = QtWidgets.QWidget()
        self.grid = QtWidgets.QGridLayout(self.grid_holder)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(3)
        self.core_graphs = []
        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self.overall)
        self.stack.addWidget(self.grid_holder)
        self.frame = GraphFrame("% Utilization over 60 seconds", "100%", self.stack)
        self.layout_.addWidget(self.frame, 1)
        small = ["Maximum speed", "Sockets", "Cores", "Logical processors", "Virtualization"]
        small += ["{} cache".format(level) for level in sorted(info.caches)]
        self.stats = StatBlock([["Utilization", "Speed"], ["Processes", "Threads", "Handles"], ["Up time"]],
                               small)
        self.layout_.addWidget(self.stats)
        self.stats.set("Maximum speed", fmt_freq(info.max_mhz))
        self.stats.set("Sockets", str(info.sockets))
        self.stats.set("Cores", str(info.cores))
        self.stats.set("Logical processors", str(info.logical))
        self.stats.set("Virtualization", info.virtualization)
        for level, size in info.caches.items():
            self.stats.set("{} cache".format(level), fmt_cache(size))

    def extend_menu(self, menu):
        sub = menu.addMenu("Change graph to")
        overall = sub.addAction("Overall utilization", lambda: self.set_logical(False))
        logical = sub.addAction("Logical processors", lambda: self.set_logical(True))
        for act, value in ((overall, False), (logical, True)):
            act.setCheckable(True)
            act.setChecked(self.logical == value)
        kernel = menu.addAction("Show kernel times", lambda: setattr(self, "show_kernel", not self.show_kernel))
        kernel.setCheckable(True)
        kernel.setChecked(self.show_kernel)
        menu.addSeparator()

    def set_logical(self, logical):
        self.logical = logical
        self.stack.setCurrentIndex(1 if logical else 0)
        self.frame.left.setText("% Utilization over 60 seconds" if not logical else "% Utilization")

    def _ensure_cores(self, count):
        if len(self.core_graphs) == count:
            return
        cols = max(1, int(round(count ** 0.5 * 1.4)))
        for idx in range(count):
            graph = HistoryGraph(self.style_, POINTS, series=2)
            graph.setMinimumSize(30, 24)
            self.grid.addWidget(graph, idx // cols, idx % cols)
            self.core_graphs.append(graph)

    def update_snapshot(self, snap):
        cpu = snap.cpu
        self.overall.push(cpu.total, cpu.kernel if self.show_kernel else None)
        self._ensure_cores(len(cpu.per_cpu))
        for graph, value, kernel in zip(self.core_graphs, cpu.per_cpu, cpu.per_cpu_kernel):
            graph.push(value, kernel if self.show_kernel else None)
        self.stats.set("Utilization", "{:.0f}%".format(cpu.total))
        self.stats.set("Speed", fmt_freq(cpu.freq_mhz))
        self.stats.set("Processes", "{:,}".format(snap.process_count))
        self.stats.set("Threads", "{:,}".format(snap.threads))
        self.stats.set("Handles", "{:,}".format(snap.handles) if snap.handles is not None else "N/A")
        self.stats.set("Up time", fmt_uptime(snap.uptime))


class MemoryPage(DetailPage):
    def __init__(self, parent=None):
        super().__init__("Memory", parent)
        self.graph = HistoryGraph(win8_style(*WIN8_MEM), POINTS)
        self.frame = GraphFrame("Memory usage", "", self.graph)
        self.layout_.addWidget(self.frame, 1)
        self.layout_.addWidget(_label("Memory composition", 9, GRAY))
        self.bar = CompositionBar(WIN8_MEM[0])
        self.layout_.addWidget(self.bar)
        self.stats = StatBlock([["In use", "Available"], ["Committed", "Cached"], ["Kernel slab", "Shared"]],
                               ["Swap used", "Swap total", "Buffers", "Page tables"])
        self.layout_.addWidget(self.stats)

    def update_snapshot(self, snap):
        m = snap.mem
        self.subtitle.setText(fmt_gb(m.total))
        self.frame.right.setText(fmt_gb(m.total))
        self.graph.push(m.percent)
        standby = max(0, m.cached - m.modified)
        free = max(0, m.total - m.used - m.modified - standby)
        self.bar.set_parts(m.used, m.modified, standby, free, m.total)
        self.stats.set("In use", fmt_gb(m.used))
        self.stats.set("Available", fmt_gb(m.available))
        self.stats.set("Committed", "{:.1f}/{:.1f} GB".format(m.commit / 2 ** 30, m.commit_limit / 2 ** 30))
        self.stats.set("Cached", fmt_gb(m.cached))
        self.stats.set("Kernel slab", "{:.0f} MB".format(m.slab / 2 ** 20) if m.slab else "N/A")
        self.stats.set("Shared", "{:.0f} MB".format(m.shared / 2 ** 20))
        self.stats.set("Swap used", fmt_gb(m.swap_used))
        self.stats.set("Swap total", fmt_gb(m.swap_total))
        self.stats.set("Buffers", "{:.0f} MB".format(m.buffers / 2 ** 20))
        self.stats.set("Page tables", "{:.0f} MB".format(m.page_tables / 2 ** 20) if m.page_tables else "N/A")


class DiskPage(DetailPage):
    def __init__(self, index, disk, parent=None):
        super().__init__("Disk {} ({})".format(index, disk.name), parent)
        self.subtitle.setText(disk.model or disk.name)
        self.active = HistoryGraph(win8_style(*WIN8_DISK), POINTS)
        self.layout_.addWidget(GraphFrame("Active time", "100%", self.active), 3)
        rate_style = win8_style(*WIN8_DISK, dashed_second=True)
        rate_style.fills = [WIN8_DISK[1], None]
        self.rate = HistoryGraph(rate_style, POINTS, series=2)
        self.rate.autoscale = True
        self.rate_frame = GraphFrame("Disk transfer rate", "", self.rate)
        self.layout_.addWidget(self.rate_frame, 2)
        self.stats = StatBlock([["Active time", "Average response time"], ["Read speed", "Write speed"]],
                               ["Capacity", "Formatted", "System disk", "Swap file"])
        self.layout_.addWidget(self.stats)

    def update_snapshot(self, disk):
        self.active.push(disk.active)
        self.rate.push(disk.read_bps, disk.write_bps)
        self.rate_frame.right.setText(fmt_rate(self.rate.maximum))
        self.stats.set("Active time", "{:.0f}%".format(disk.active))
        self.stats.set("Average response time", "{:.1f} ms".format(disk.response_ms))
        self.stats.set("Read speed", fmt_rate(disk.read_bps))
        self.stats.set("Write speed", fmt_rate(disk.write_bps))
        self.stats.set("Capacity", fmt_gb(disk.capacity) if disk.capacity else "Unknown")
        self.stats.set("Formatted", fmt_gb(disk.formatted) if disk.formatted else "N/A")
        self.stats.set("System disk", "Yes" if disk.system_disk else "No")
        self.stats.set("Swap file", "Yes" if disk.page_file else "No")
        if disk.mountpoints:
            self.subtitle.setText("{}  —  {}".format(disk.model or disk.name, ", ".join(disk.mountpoints[:3])))


class NetPage(DetailPage):
    def __init__(self, net, parent=None):
        super().__init__(net.kind, parent)
        self.subtitle.setText(net.name)
        style = win8_style(*WIN8_NET, dashed_second=True)
        style.fills = [WIN8_NET[1], None]
        self.graph = HistoryGraph(style, POINTS, series=2)
        self.graph.autoscale = True
        self.frame = GraphFrame("Throughput", "", self.graph)
        self.layout_.addWidget(self.frame, 1)
        self.stats = StatBlock([["Send", "Receive"]],
                               ["Adapter name", "Connection type", "Link speed", "IPv4 address", "IPv6 address"])
        self.layout_.addWidget(self.stats)

    def update_snapshot(self, net):
        self.graph.push(net.sent_bps * 8, net.recv_bps * 8)
        self.graph.maximum = nice_ceiling(max(self.graph.maximum, 100e3))
        self.frame.right.setText(fmt_bits(self.graph.maximum / 8))
        self.stats.set("Send", fmt_bits(net.sent_bps))
        self.stats.set("Receive", fmt_bits(net.recv_bps))
        self.stats.set("Adapter name", net.name)
        self.stats.set("Connection type", net.kind)
        self.stats.set("Link speed", fmt_link_speed(net.speed_mbps))
        self.stats.set("IPv4 address", net.ipv4 or "Not connected")
        self.stats.set("IPv6 address", net.ipv6 or "Not connected")


class PerformanceTab(QtWidgets.QWidget):
    summary_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("win8page")
        self.summary = False
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(0)
        self.side_widget = QtWidgets.QWidget()
        self.side_widget.setObjectName("win8page")
        self.side = QtWidgets.QVBoxLayout(self.side_widget)
        self.side.setContentsMargins(4, 6, 4, 6)
        self.side.setSpacing(2)
        self.side.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.side_widget)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(220)
        scroll.setStyleSheet("QScrollArea { border: none; border-right: 1px solid #E5E5E5; }")
        self.scroll = scroll
        body.addWidget(scroll)
        self.pages = QtWidgets.QStackedWidget()
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)

        self.fewer = LinkButton("Fewer details", Qt.ArrowType.UpArrow)
        resmon = LinkButton("Open Resource Monitor")
        resmon.clicked.connect(self._resmon)
        self.bottom = bottom_bar([self.fewer, _separator(), resmon], [])
        outer.addWidget(self.bottom)

        self.items = {}
        self.page_for = {}
        self.cpu_info = sysinfo.get_cpu_info()
        self._add("cpu", "CPU", WIN8_CPU, CpuPage(self.cpu_info))
        self._add("mem", "Memory", WIN8_MEM, MemoryPage())
        self.disk_index = {}
        self.select("cpu")

    def _add(self, key, title, colors, page, series=1):
        item = SideItem(key, title, colors, series)
        item.clicked.connect(self.select)
        item.double_clicked.connect(self.toggle_summary)
        self.side.insertWidget(self.side.count() - 1, item)
        self.items[key] = item
        self.pages.addWidget(page)
        self.page_for[key] = page
        return item

    def _remove(self, key):
        item = self.items.pop(key)
        page = self.page_for.pop(key)
        item.setParent(None)
        self.pages.removeWidget(page)
        page.deleteLater()

    def select(self, key):
        for item_key, item in self.items.items():
            item.set_selected(item_key == key)
        self.pages.setCurrentWidget(self.page_for[key])
        self.current = key

    def toggle_summary(self):
        """Double-clicking the sidebar shows only the sidebar (summary view)."""
        self.summary = not self.summary
        self.pages.setVisible(not self.summary)
        self.bottom.setVisible(not self.summary)
        self.scroll.setStyleSheet("QScrollArea { border: none; }" if self.summary else
                                  "QScrollArea { border: none; border-right: 1px solid #E5E5E5; }")
        self.summary_toggled.emit(self.summary)

    def _resmon(self):
        try:
            actions.open_resource_monitor()
        except OSError as exc:
            show_error(self, "Resource Monitor", exc)

    def update_snapshot(self, snap):
        cpu = snap.cpu
        self.items["cpu"].graph.push(cpu.total)
        self.items["cpu"].set_text("{:.0f}% {}".format(cpu.total, fmt_freq(cpu.freq_mhz) if cpu.freq_mhz else ""))
        self.page_for["cpu"].update_snapshot(snap)
        mem = snap.mem
        self.items["mem"].graph.push(mem.percent)
        self.items["mem"].set_text("{:.1f}/{:.1f} GB ({:.0f}%)".format(
            mem.used / 2 ** 30, mem.total / 2 ** 30, mem.percent))
        self.page_for["mem"].update_snapshot(snap)

        keys = set()
        for disk in snap.disks:
            key = "disk:" + disk.name
            keys.add(key)
            if key not in self.items:
                idx = self.disk_index.setdefault(disk.name, len(self.disk_index))
                self._add(key, "Disk {} ({})".format(idx, disk.name), WIN8_DISK, DiskPage(idx, disk))
            self.items[key].graph.push(disk.active)
            self.items[key].set_text("{:.0f}%".format(disk.active))
            self.page_for[key].update_snapshot(disk)
        for net in snap.nets:
            if not net.is_up:
                continue
            key = "net:" + net.name
            keys.add(key)
            if key not in self.items:
                item = self._add(key, net.kind, WIN8_NET, NetPage(net), series=2)
                item.graph.autoscale = True
            item = self.items[key]
            item.graph.push(net.sent_bps * 8, net.recv_bps * 8)
            item.graph.maximum = nice_ceiling(max(item.graph.maximum, 100e3))
            item.set_text(net.name, "S: {} R: {}".format(fmt_bits(net.sent_bps), fmt_bits(net.recv_bps)))
            self.page_for[key].update_snapshot(net)
        for key in [k for k in self.items if k.startswith(("disk:", "net:")) and k not in keys]:
            if self.current == key:
                self.select("cpu")
            self._remove(key)


def _separator():
    line = QtWidgets.QFrame()
    line.setFrameShape(QtWidgets.QFrame.Shape.VLine)
    line.setStyleSheet("color: #C0C0C0;")
    line.setFixedHeight(14)
    return line
