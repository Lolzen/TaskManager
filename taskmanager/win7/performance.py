"""Windows 7 *Performance* and *Networking* tabs."""

from ..backend import actions
from ..backend.formatting import MB, fmt_link_speed, fmt_uptime
from ..backend.sampler import ASSUMED_LINK_MBPS
from ..qt import QtWidgets, Qt
from ..widgets import tux as tuxui
from ..widgets.dialogs import show_error
from ..widgets.graph import WIN7_KERNEL_STYLE, WIN7_STYLE, GraphStyle, HistoryGraph, LedMeter, nice_ceiling
from ..widgets.tree import ItemSync, RIGHT, make_tree, set_cell

POINTS = 100


def _group(title, widget=None, layout=None):
    box = QtWidgets.QGroupBox(title)
    lay = layout or QtWidgets.QVBoxLayout()
    lay.setContentsMargins(6, 4, 6, 6)
    if widget is not None:
        lay.addWidget(widget)
    box.setLayout(lay)
    return box


class StatsBox(QtWidgets.QGroupBox):
    """Label/value grid such as *Physical Memory (MB)*."""

    def __init__(self, title, labels):
        super().__init__(title)
        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(8, 2, 8, 4)
        grid.setVerticalSpacing(0)
        self.values = {}
        for row, label in enumerate(labels):
            grid.addWidget(QtWidgets.QLabel(label), row, 0)
            value = QtWidgets.QLabel("0")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(value, row, 1)
            self.values[label] = value

    def set(self, label, text):
        self.values[label].setText(text)


class PerformanceTab(QtWidgets.QWidget):
    def __init__(self, tux=False, parent=None):
        super().__init__(parent)
        self.tux = tux
        self.one_graph_per_cpu = True
        self.show_kernel = False
        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        self.cpu_meter = LedMeter()
        self.mem_meter = LedMeter()
        grid.addWidget(_group("CPU Usage", self.cpu_meter), 0, 0)
        self.cpu_box = QtWidgets.QHBoxLayout()
        self.cpu_box.setSpacing(4)
        grid.addWidget(_group("CPU Usage History", layout=self.cpu_box), 0, 1)
        grid.addWidget(_group("Memory", self.mem_meter), 1, 0)
        self.mem_graph = HistoryGraph(WIN7_STYLE, POINTS)
        grid.addWidget(_group("Physical Memory Usage History", self.mem_graph), 1, 1)
        self.cpu_graphs = []

        bottom = QtWidgets.QHBoxLayout()
        left = QtWidgets.QVBoxLayout()
        self.phys = StatsBox("Physical Memory (MB)", ["Total", "Cached", "Available", "Free"])
        self.kern = StatsBox("Kernel Memory (MB)", ["Slab", "Kernel Stack"])
        left.addWidget(self.phys)
        left.addWidget(self.kern)
        self.linux = None
        if tux:
            self.linux = StatsBox("Linux", ["Load Average", "CPU Pressure", "Context Switches/s", "Temperature"])
            left.addWidget(self.linux)
        right = QtWidgets.QVBoxLayout()
        self.system = StatsBox("System", ["Handles", "Threads", "Processes", "Up Time", "Commit (MB)"])
        right.addWidget(self.system)
        button = QtWidgets.QPushButton("Resource Monitor...")
        button.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon))
        button.clicked.connect(self._resmon)
        right.addWidget(button, 0, Qt.AlignmentFlag.AlignRight)
        right.addStretch(1)
        bottom.addLayout(left, 1)
        bottom.addLayout(right, 1)
        grid.addLayout(bottom, 2, 0, 1, 2)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(1, 1)

    def _resmon(self):
        try:
            actions.open_resource_monitor()
        except OSError as exc:
            show_error(self, "Resource Monitor", exc)

    def _ensure_cpu_graphs(self, count):
        wanted = count if self.one_graph_per_cpu else 1
        if len(self.cpu_graphs) == wanted:
            return
        self._clear_cpu_graphs()
        style = WIN7_KERNEL_STYLE if self.show_kernel else WIN7_STYLE
        for _ in range(wanted):
            graph = HistoryGraph(style, POINTS, series=2)
            graph.setMinimumWidth(30)
            self.cpu_box.addWidget(graph)
            self.cpu_graphs.append(graph)

    def _clear_cpu_graphs(self):
        for graph in self.cpu_graphs:
            graph.setParent(None)
            graph.deleteLater()
        self.cpu_graphs = []

    def set_cpu_mode(self, per_cpu):
        self.one_graph_per_cpu = per_cpu
        self._clear_cpu_graphs()

    def set_show_kernel(self, show):
        self.show_kernel = show
        self.cpu_meter.show_kernel = show
        for graph in self.cpu_graphs:
            graph.gstyle = WIN7_KERNEL_STYLE if show else WIN7_STYLE
            graph.update()

    def update_snapshot(self, snap):
        cpu = snap.cpu
        self.cpu_meter.set_value(cpu.total, "{:.0f} %".format(cpu.total), cpu.kernel)
        self._ensure_cpu_graphs(len(cpu.per_cpu))
        if self.one_graph_per_cpu:
            for graph, value, kernel in zip(self.cpu_graphs, cpu.per_cpu, cpu.per_cpu_kernel):
                graph.push(value, kernel if self.show_kernel else None)
        elif self.cpu_graphs:
            self.cpu_graphs[0].push(cpu.total, cpu.kernel if self.show_kernel else None)

        mem = snap.mem
        used_gb = mem.used / 2 ** 30
        self.mem_meter.set_value(mem.percent, "{:.2f} GB".format(used_gb) if used_gb < 10 else "{:.1f} GB".format(used_gb))
        self.mem_graph.push(mem.percent)

        self.phys.set("Total", "{:,}".format(mem.total // MB))
        self.phys.set("Cached", "{:,}".format(mem.cached // MB))
        self.phys.set("Available", "{:,}".format(mem.available // MB))
        self.phys.set("Free", "{:,}".format(mem.free // MB))
        self.kern.set("Slab", "{:,}".format(mem.slab // MB) if mem.slab else "N/A")
        self.kern.set("Kernel Stack", "{:,}".format(mem.kernel_stack // MB) if mem.kernel_stack else "N/A")
        self.system.set("Handles", "{:,}".format(snap.handles) if snap.handles is not None else "N/A")
        self.system.set("Threads", "{:,}".format(snap.threads))
        self.system.set("Processes", "{:,}".format(snap.process_count))
        self.system.set("Up Time", fmt_uptime(snap.uptime))
        self.system.set("Commit (MB)", "{:,} / {:,}".format(mem.commit // MB, mem.commit_limit // MB))
        if self.linux is not None and snap.tux is not None:
            values = tuxui.cpu_values(snap.tux)
            self.linux.set("Load Average", values["Load average"])
            self.linux.set("CPU Pressure", values["CPU pressure"])
            self.linux.set("Context Switches/s", values["Context switches/s"])
            self.linux.set("Temperature", values["Temperature"])


class ScaledGraph(QtWidgets.QWidget):
    """Windows 7 networking graph with its percentage scale on the left."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        scale = QtWidgets.QVBoxLayout()
        self.top = QtWidgets.QLabel("100 %")
        self.mid = QtWidgets.QLabel("50 %")
        self.bottom = QtWidgets.QLabel("0 %")
        for label in (self.top, self.mid, self.bottom):
            label.setAlignment(Qt.AlignmentFlag.AlignRight)
        scale.addWidget(self.top)
        scale.addStretch(1)
        scale.addWidget(self.mid)
        scale.addStretch(1)
        scale.addWidget(self.bottom)
        holder = QtWidgets.QWidget()
        holder.setLayout(scale)
        holder.setFixedWidth(64)
        layout.addWidget(holder)
        style = GraphStyle(lines=["#00FF00", "#FFFF00", "#FF0000"], fills=[None, None, None],
                           dashed=[False, False, False])
        self.graph = HistoryGraph(style, POINTS, series=3)
        self.graph.setMinimumHeight(90)
        layout.addWidget(self.graph, 1)

    def push(self, total, sent, recv):
        self.graph.push(total, sent, recv)
        peak = max((v for s in self.graph.data for v in s if v is not None), default=0.0)
        top = min(100.0, nice_ceiling(max(peak, 0.5)))
        self.graph.maximum = top
        self.top.setText("{:g} %".format(top))
        self.mid.setText("{:g} %".format(top / 2))


class NetworkingTab(QtWidgets.QWidget):
    def __init__(self, tux=False, parent=None):
        super().__init__(parent)
        self.tux = tux
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.graph_area = QtWidgets.QWidget()
        self.graph_layout = QtWidgets.QVBoxLayout(self.graph_area)
        self.graph_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(self.graph_area)
        layout.addWidget(scroll, 3)
        self.empty = QtWidgets.QLabel("No active network adapters found.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.graph_layout.addWidget(self.empty)
        self.graphs = {}
        self.table = make_tree(["Adapter Name", "Network Utilization", "Link Speed", "State",
                                "Bytes Sent/Interval", "Bytes Received/Interval"] +
                               (tuxui.NET_KEYS if tux else []))
        header = self.table.header()
        for col, width in enumerate((150, 120, 80, 90, 120, 130, 130, 50, 60, 100, 100)):
            header.resizeSection(col, width)
        self.sync = ItemSync(self.table)
        layout.addWidget(self.table, 1)
        self.show_sent_recv = False

    def update_snapshot(self, snap):
        nets = [n for n in snap.nets if n.is_up]
        self.empty.setVisible(not nets)
        for name in [n for n in self.graphs if n not in {x.name for x in nets}]:
            self.graphs.pop(name).setParent(None)
        for net in nets:
            box = self.graphs.get(net.name)
            if box is None:
                box = _group("{} ({})".format(net.kind, net.name), ScaledGraph())
                self.graph_layout.addWidget(box)
                self.graphs[net.name] = box
            graph = box.findChild(ScaledGraph)
            sent = recv = None
            if self.show_sent_recv:
                speed = (net.speed_mbps or ASSUMED_LINK_MBPS) * 1e6
                sent = min(100.0, 100.0 * net.sent_bps * 8 / speed)
                recv = min(100.0, 100.0 * net.recv_bps * 8 / speed)
            graph.push(net.utilization, sent, recv)

        self.sync.begin()
        for net in snap.nets:
            item = self.sync.get(net.name)
            set_cell(item, 0, "{} ({})".format(net.kind, net.name))
            set_cell(item, 1, "{:.2f} %".format(net.utilization), net.utilization, RIGHT)
            set_cell(item, 2, fmt_link_speed(net.speed_mbps), net.speed_mbps, RIGHT)
            set_cell(item, 3, "Connected" if net.is_up else "Disconnected")
            set_cell(item, 4, "{:,}".format(int(net.sent_bps * snap.interval)), net.sent_bps, RIGHT)
            set_cell(item, 5, "{:,}".format(int(net.recv_bps * snap.interval)), net.recv_bps, RIGHT)
            if self.tux and snap.tux is not None:
                for offset, (key, value) in enumerate(tuxui.net_values(snap.tux, net.name).items()):
                    set_cell(item, 6 + offset, value)
        self.sync.end()
