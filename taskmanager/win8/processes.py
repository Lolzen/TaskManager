"""Windows 8 *Processes*, *Users* and *Details* tabs."""

import os
import socket
from urllib.parse import quote_plus

from ..backend import actions, sysinfo
from ..backend.formatting import MB, fmt_cpu_time, fmt_disk_rate, fmt_kb, fmt_mem_mb
from ..backend.sampler import KIND_APP, KIND_BACKGROUND, KIND_SYSTEM
from ..core import bulk_update
from ..qt import QtCore, QtWidgets, Qt, Signal
from ..widgets import tux as tuxui
from ..widgets.dialogs import PropertiesDialog, confirm, confirm_end, guarded, process_menu
from ..widgets.tree import KEY_ROLE, LEFT, RIGHT, ColumnChooser, SortItem, make_tree, set_cell
from .common import (APP_ICON, PROC_ICON, SYS_ICON, USER_ICON, GroupItem, LinkButton, bottom_bar,
                     column_menu, icon_for, install_header, set_heat)

GROUPS = [(KIND_APP, "Apps"), (KIND_BACKGROUND, "Background processes"), (KIND_SYSTEM, "System processes")]
NO_NET = "–"
NO_NET_TIP = "Per-process network usage is not reported by this operating system."


def fmt_cpu8(value):
    return "0%" if value < 0.05 else "{:.1f}%".format(value)


def fmt_disk8(bps):
    return "0 MB/s" if bps < 0.05 * MB else fmt_disk_rate(bps)


POWER_LEVELS = ["Very low", "Low", "Moderate", "High", "Very high"]
POWER_LIMITS = [1.0, 5.0, 15.0, 35.0]


def power_score(cpu, gpu, disk_bps):
    """Estimate of a process' power draw. Like Windows 10, this is derived from
    CPU, GPU and disk activity rather than measured."""
    return cpu + 0.6 * gpu + 0.5 * disk_bps / MB


def power_level(score):
    for idx, limit in enumerate(POWER_LIMITS):
        if score < limit:
            return idx
    return len(POWER_LIMITS)


_arch_cache = {}


def architecture(proc):
    if proc.exe not in _arch_cache:
        _arch_cache[proc.exe] = sysinfo.binary_architecture(proc.exe) if proc.exe else ""
    return _arch_cache[proc.exe]


def full_account_name(user):
    """``Full Name (user)`` as Windows 10 shows with *Show full account name*."""
    try:
        import pwd
        gecos = pwd.getpwnam(user).pw_gecos.split(",")[0].strip()
    except (ImportError, KeyError):
        gecos = ""
    return "{} ({})".format(gecos, user) if gecos else user


class TreeTab(QtWidgets.QWidget):
    """Common plumbing: tree + items keyed by string, multi-level diffing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("win8page")
        self.items = {}
        self._seen = set()
        self.snap = None

    def node(self, key, parent=None, factory=SortItem, *args):
        item = self.items.get(key)
        if item is not None and item.parent() is not parent:
            self._detach(item)
            item = None
        if item is None:
            item = factory(*args)
            item.setData(0, KEY_ROLE, key)
            if parent is None:
                self.tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
            self.items[key] = item
        self._seen.add(key)
        return item

    def _detach(self, item):
        parent = item.parent()
        if parent is not None:
            parent.removeChild(item)
        else:
            idx = self.tree.indexOfTopLevelItem(item)
            if idx >= 0:
                self.tree.takeTopLevelItem(idx)

    def begin(self):
        self._seen = set()

    def end(self):
        for key in [k for k in self.items if k not in self._seen]:
            self._detach(self.items.pop(key))

    def current_key(self):
        items = self.tree.selectedItems()
        return items[0].data(0, KEY_ROLE) if items else None


class MetricTreeTab(TreeTab):
    """Shared by *Processes* and *Users*: CPU / Memory / Disk / Network heat map."""

    METRIC_COLS = ()  # (cpu, mem, disk, net) column indexes
    GPU_COLS = ()  # Windows 10: (gpu, gpu engine)

    def fill_gpu(self, item, gpu, engine):
        if not self.GPU_COLS:
            return
        c_gpu, c_engine = self.GPU_COLS
        set_cell(item, c_gpu, fmt_cpu8(gpu), gpu, RIGHT)
        set_cell(item, c_engine, engine if gpu >= 0.05 else "")
        set_heat(item, c_gpu, gpu / 40.0)

    def fill_metrics(self, item, cpu, mem, disk, total_mem):
        c_cpu, c_mem, c_disk, c_net = self.METRIC_COLS
        set_cell(item, c_cpu, fmt_cpu8(cpu), cpu, RIGHT)
        set_cell(item, c_mem, fmt_mem_mb(mem), mem, RIGHT)
        set_cell(item, c_disk, fmt_disk8(disk), disk, RIGHT)
        set_cell(item, c_net, NO_NET, 0, RIGHT)
        item.setToolTip(c_net, NO_NET_TIP)
        set_heat(item, c_cpu, cpu / 40.0)
        set_heat(item, c_mem, mem / max(1, total_mem) / 0.08)
        set_heat(item, c_disk, disk / (5.0 * MB))
        set_heat(item, c_net, 0)

    def update_header(self, snap):
        c_cpu, c_mem, c_disk, c_net = self.METRIC_COLS
        disk_active = max((d.active for d in snap.disks), default=0.0)
        net_util = max((n.utilization for n in snap.nets), default=0.0)
        self.header.set_metric(c_cpu, "{:.0f}%".format(snap.cpu.total), snap.cpu.total / 100.0)
        self.header.set_metric(c_mem, "{:.0f}%".format(snap.mem.percent), snap.mem.percent / 100.0)
        self.header.set_metric(c_disk, "{:.0f}%".format(disk_active), disk_active / 100.0)
        self.header.set_metric(c_net, "{:.0f}%".format(net_util), net_util / 100.0)
        if self.GPU_COLS:
            gpu_util = max((g.utilization for g in snap.gpus), default=0.0)
            self.header.set_metric(self.GPU_COLS[0], "{:.0f}%".format(gpu_util), gpu_util / 100.0)


PROC_COLUMNS = ["Name", "Type", "Status", "PID", "Process name", "Command line", "CPU", "Memory", "Disk", "Network"]
PROC_HIDDEN = ["Type", "PID", "Process name", "Command line"]
TYPE_LABELS = {KIND_APP: "App", KIND_BACKGROUND: "Background process", KIND_SYSTEM: "System process"}


WIN10_PROC_COLUMNS = ["GPU", "GPU engine", "Power usage", "Power usage trend"]
TUX_PROC_COLUMNS = ["systemd unit", "Container", "OOM score", "Memory (USS)"]


class ProcessesTab(MetricTreeTab):
    METRIC_COLS = (6, 7, 8, 9)
    goto_details = Signal(int)
    used = Signal()

    def __init__(self, win10=False, tux=False, parent=None):
        super().__init__(parent)
        self.win10 = win10
        self.tux = tux
        self.group_by_type = True
        self.trends = {}  # row key -> smoothed power score (Windows 10 *Power usage trend*)
        columns = PROC_COLUMNS + (WIN10_PROC_COLUMNS if win10 else [])
        self.tux_col = len(columns)
        columns = columns + (TUX_PROC_COLUMNS if tux else [])
        if win10:
            self.GPU_COLS = (10, 11)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.tree = make_tree(columns, root_decorated=True)
        self.header = install_header(self.tree, right_aligned=[3, 6, 7, 8, 9, 10])
        self.tree.setHeaderLabels(columns)
        for idx, width in enumerate((250, 120, 80, 55, 110, 250, 70, 85, 75, 75, 60, 100, 90, 120)):
            if idx < len(columns):
                self.header.resizeSection(idx, width)
        if tux:
            self.header.right_aligned |= {self.tux_col + 2, self.tux_col + 3}
            for offset, width in enumerate((170, 80, 75, 95)):
                self.header.resizeSection(self.tux_col + offset, width)
        for title in PROC_HIDDEN:
            self.header.setSectionHidden(columns.index(title), True)
        column_menu(self.tree, columns)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemSelectionChanged.connect(self._sel_changed)
        self.tree.setIndentation(14)
        layout.addWidget(self.tree, 1)
        self.groups = {}
        self.apps = {}  # app key -> [ProcInfo]

        self.end_btn = QtWidgets.QPushButton("End task")
        self.end_btn.clicked.connect(self.end_task)
        self.end_btn.setEnabled(False)
        self.fewer = LinkButton("Fewer details", Qt.ArrowType.UpArrow)
        layout.addWidget(bottom_bar([self.fewer], [self.end_btn]))

    def set_group_by_type(self, enabled):
        self.group_by_type = enabled
        for key in list(self.items):
            self._detach(self.items.pop(key))
        self.groups = {}
        if self.snap is not None:
            self.update_snapshot(self.snap)

    def update_snapshot(self, snap):
        self.snap = snap
        total = snap.mem.total
        apps = {}
        singles = {KIND_BACKGROUND: [], KIND_SYSTEM: [], KIND_APP: []}
        for proc in snap.procs.values():
            if proc.kind == KIND_APP and proc.app_id:
                apps.setdefault(proc.app_id, []).append(proc)
            else:
                singles[proc.kind].append(proc)
        self.apps = {"app:" + k: v for k, v in apps.items()}

        with bulk_update(self.tree):
            self.begin()
            parents = {}
            if self.group_by_type:
                counts = {KIND_APP: len(apps), KIND_BACKGROUND: len(singles[KIND_BACKGROUND]),
                          KIND_SYSTEM: len(singles[KIND_SYSTEM])}
                for rank, (kind, title) in enumerate(GROUPS):
                    if not counts[kind]:
                        continue
                    group = self.node("group:" + kind, None, GroupItem, rank, title)
                    group.set_count(counts[kind])
                    if kind not in self.groups:
                        group.setExpanded(True)
                        self.groups[kind] = group
                    parents[kind] = group

            for app_id, procs in apps.items():
                procs.sort(key=lambda p: p.create_time)
                item = self.node("app:" + app_id, parents.get(KIND_APP))
                name = procs[0].app_name + (" ({})".format(len(procs)) if len(procs) > 1 else "")
                set_cell(item, 0, name, procs[0].app_name.lower())
                if item.icon(0).isNull():
                    item.setIcon(0, icon_for(procs[0].icon, APP_ICON))
                self._fill_static(item, procs[0], KIND_APP)
                hung = any(p.status == "Suspended" for p in procs)
                set_cell(item, 2, "Suspended" if hung else "")
                if self.tux:
                    self.fill_tux(item, procs)
                self.fill_metrics(item, sum(p.cpu for p in procs), sum(p.mem_private for p in procs),
                                  sum(p.disk_bps for p in procs), total)
                if self.win10:
                    busiest = max(procs, key=lambda p: p.gpu)
                    gpu = min(100.0, sum(p.gpu for p in procs))
                    self.fill_gpu(item, gpu, busiest.gpu_engine)
                    self.fill_power(item, "app:" + app_id, sum(p.cpu for p in procs), gpu,
                                    sum(p.disk_bps for p in procs), snap.interval)
                if len(procs) > 1:
                    for proc in procs:
                        child = self.node("pid:{}".format(proc.pid), item)
                        self._fill_proc(child, proc, total)

            for kind in (KIND_BACKGROUND, KIND_SYSTEM, KIND_APP):
                for proc in singles[kind]:
                    item = self.node("pid:{}".format(proc.pid), parents.get(kind))
                    self._fill_proc(item, proc, total)
            self.end()
        if self.win10:
            self.trends = {k: v for k, v in self.trends.items() if k in self.items}
        self.update_header(snap)
        self._sel_changed()

    def fill_power(self, item, key, cpu, gpu, disk, interval):
        score = power_score(cpu, gpu, disk)
        # exponential average over roughly two minutes
        alpha = min(1.0, max(interval, 0.1) / 120.0)
        trend = self.trends.get(key, score) * (1 - alpha) + score * alpha
        self.trends[key] = trend
        level, trend_level = power_level(score), power_level(trend)
        set_cell(item, 12, POWER_LEVELS[level], level)
        set_cell(item, 13, POWER_LEVELS[trend_level], trend_level)
        set_heat(item, 12, level / 4.0)
        set_heat(item, 13, trend_level / 4.0)

    def fill_tux(self, item, procs):
        extras = [p.tux for p in procs if p.tux is not None]
        col = self.tux_col
        units = sorted({e.unit for e in extras if e.unit})
        set_cell(item, col, ", ".join(units[:2]) + (" \u2026" if len(units) > 2 else ""))
        set_cell(item, col + 1, next((e.container for e in extras if e.container), ""))
        oom = max((e.oom_score for e in extras), default=0)
        set_cell(item, col + 2, str(oom) if extras else "", oom, RIGHT)
        uss = sum(e.uss for e in extras)
        set_cell(item, col + 3, fmt_mem_mb(uss) if uss else "", uss, RIGHT)

    def _fill_static(self, item, proc, kind):
        set_cell(item, 1, TYPE_LABELS[kind])
        set_cell(item, 3, str(proc.pid), proc.pid, RIGHT)
        set_cell(item, 4, proc.name)
        set_cell(item, 5, proc.cmdline)

    def _fill_proc(self, item, proc, total):
        name = proc.app_name or proc.name
        set_cell(item, 0, name, name.lower())
        if item.icon(0).isNull():
            fallback = SYS_ICON if proc.kind == KIND_SYSTEM else PROC_ICON
            item.setIcon(0, icon_for(proc.icon, fallback))
        self._fill_static(item, proc, proc.kind)
        set_cell(item, 2, "Suspended" if proc.status == "Suspended" else "")
        if self.tux:
            set_cell(item, 2, tuxui.proc_status(proc, item.text(2)))
            self.fill_tux(item, [proc])
        self.fill_metrics(item, proc.cpu, proc.mem_private, proc.disk_bps, total)
        if self.win10:
            self.fill_gpu(item, proc.gpu, proc.gpu_engine)
            self.fill_power(item, "pid:{}".format(proc.pid), proc.cpu, proc.gpu, proc.disk_bps,
                            self.snap.interval if self.snap else 1.0)

    # -- actions ----------------------------------------------------------------
    def _selection(self):
        key = self.current_key()
        if not key or key.startswith("group:") or self.snap is None:
            return None, []
        if key.startswith("app:"):
            return key, self.apps.get(key, [])
        proc = self.snap.procs.get(int(key.split(":", 1)[1]))
        return key, [proc] if proc else []

    def _sel_changed(self):
        _key, procs = self._selection()
        self.end_btn.setEnabled(bool(procs))

    def end_task(self):
        key, procs = self._selection()
        if not procs:
            return
        if key.startswith("pid:") and procs[0].kind == KIND_SYSTEM:
            if not confirm_end(self, procs[0].name, win8=True):
                return
        for proc in procs:
            if not guarded(self, "Unable to end task", actions.end_process, proc.pid):
                break

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        key, procs = self._selection()
        if not procs:
            return
        proc = procs[0]
        menu = QtWidgets.QMenu(self)
        if item.childCount():
            menu.addAction("Collapse" if item.isExpanded() else "Expand",
                           lambda: item.setExpanded(not item.isExpanded()))
        if key.startswith("app:"):
            windows = actions.list_windows() or []
            pids = {p.pid for p in procs}
            target = next((w for w in windows if w[1] in pids), None)
            if target is not None:
                menu.addAction("Switch to", lambda: (actions.activate_window(target[0]), self.used.emit()))
        menu.addAction("End task", self.end_task)
        menu.addSeparator()
        menu.addAction("Go to details", lambda: self.goto_details.emit(proc.pid))
        menu.addAction("Open file location", lambda: guarded(self, "Open file location",
                                                             actions.open_file_location, proc.exe))
        menu.addAction("Search online", lambda: search_online(self, proc.app_name or proc.name))
        menu.addAction("Properties", lambda: PropertiesDialog(proc, self).exec())
        menu.exec(self.tree.viewport().mapToGlobal(pos))


def search_online(parent, term):
    guarded(parent, "Search online", actions.open_path,
            "https://duckduckgo.com/?q=" + quote_plus(term + " process"))


USER_COLUMNS = ["User", "ID", "Session", "Client name", "Status", "CPU", "Memory", "Disk", "Network"]


class UsersTab(MetricTreeTab):
    METRIC_COLS = (5, 6, 7, 8)

    def __init__(self, win10=False, tux=False, parent=None):
        super().__init__(parent)
        self.win10 = win10
        self.tux = tux
        self.full_names = False
        columns = USER_COLUMNS + (["GPU", "GPU engine"] if win10 else [])
        self.tux_col = len(columns)
        columns = columns + (tuxui.USER_COLUMNS if tux else [])
        if win10:
            self.GPU_COLS = (9, 10)
        self.own_user = None
        try:
            import pwd
            self.own_user = pwd.getpwuid(os.getuid()).pw_name
        except (ImportError, KeyError):
            self.own_user = os.environ.get("USER", "")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.tree = make_tree(columns, root_decorated=True)
        self.header = install_header(self.tree, right_aligned=[1, 5, 6, 7, 8, 9])
        self.tree.setHeaderLabels(columns)
        for idx, width in enumerate((230, 40, 80, 110, 90, 70, 85, 75, 75, 60, 100)):
            if idx < len(columns):
                self.header.resizeSection(idx, width)
        for idx in (1, 2, 3):
            self.header.setSectionHidden(idx, True)
        column_menu(self.tree, columns, always=("User",))
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.customContextMenuRequested.connect(self._menu)
        layout.addWidget(self.tree, 1)
        self.sessions = {}
        self.disconnect_btn = QtWidgets.QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.sign_off)
        self.fewer = LinkButton("Fewer details", Qt.ArrowType.UpArrow)
        layout.addWidget(bottom_bar([self.fewer], [self.disconnect_btn]))

    def update_snapshot(self, snap):
        self.snap = snap
        sessions = {}
        for idx, user in enumerate(snap.users):
            sessions.setdefault(user.name, (idx + 1, user))
        if self.own_user and self.own_user not in sessions:
            sessions[self.own_user] = (0, None)
        self.sessions = sessions
        by_user = {}
        for proc in snap.procs.values():
            if proc.username in sessions:
                by_user.setdefault(proc.username, []).append(proc)
        total = snap.mem.total
        with bulk_update(self.tree):
            self.begin()
            for name, (sid, session) in sessions.items():
                procs = by_user.get(name, [])
                item = self.node("user:" + name)
                label = full_account_name(name) if self.full_names else name
                set_cell(item, 0, "{} ({})".format(label, len(procs)), name.lower())
                if item.icon(0).isNull():
                    item.setIcon(0, icon_for("user-identity", USER_ICON))
                set_cell(item, 1, str(sid), sid, RIGHT)
                set_cell(item, 2, (session.terminal if session else "") or "Console")
                set_cell(item, 3, (session.host if session else "") or socket.gethostname())
                set_cell(item, 4, "")
                if self.tux:
                    for offset, value in enumerate(tuxui.account_info(name)):
                        set_cell(item, self.tux_col + offset, value)
                self.fill_metrics(item, sum(p.cpu for p in procs), sum(p.mem_private for p in procs),
                                  sum(p.disk_bps for p in procs), total)
                if procs:
                    busiest = max(procs, key=lambda p: p.gpu)
                    self.fill_gpu(item, min(100.0, sum(p.gpu for p in procs)), busiest.gpu_engine)
                for proc in procs:
                    child = self.node("pid:{}".format(proc.pid), item)
                    label = proc.app_name or proc.name
                    set_cell(child, 0, label, label.lower())
                    if child.icon(0).isNull():
                        child.setIcon(0, icon_for(proc.icon, APP_ICON if proc.app_id else PROC_ICON))
                    status = "Suspended" if proc.status == "Suspended" else ""
                    set_cell(child, 4, tuxui.proc_status(proc, status) if self.tux else status)
                    self.fill_metrics(child, proc.cpu, proc.mem_private, proc.disk_bps, total)
                    self.fill_gpu(child, proc.gpu, proc.gpu_engine)
            self.end()
        self.update_header(snap)

    def _session(self):
        key = self.current_key()
        if not key or not key.startswith("user:"):
            return None
        return self.sessions.get(key[5:], (0, None))[1]

    def sign_off(self):
        session = self._session()
        if session is None:
            return
        if confirm(self, "Task Manager", "Are you sure you want to sign out {}?".format(session.name),
                   "Any unsaved data may be lost.", "Sign out user"):
            guarded(self, "Sign out", actions.logoff_session, session)

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        menu = QtWidgets.QMenu(self)
        key = item.data(0, KEY_ROLE)
        if key.startswith("user:"):
            session = self._session()
            menu.addAction("Collapse" if item.isExpanded() else "Expand",
                           lambda: item.setExpanded(not item.isExpanded()))
            menu.addAction("Disconnect", self.sign_off).setEnabled(session is not None)
            menu.addAction("Sign off", self.sign_off).setEnabled(session is not None)
            menu.addSeparator()

            def message():
                text, ok = QtWidgets.QInputDialog.getMultiLineText(self, "Send message", "Message:")
                if ok and text.strip():
                    guarded(self, "Send message", actions.send_message, session, text)

            menu.addAction("Send message", message).setEnabled(session is not None)
        else:
            proc = self.snap.procs.get(int(key.split(":")[1])) if self.snap else None
            if proc is None:
                return
            menu = process_menu(self, proc, win8=True)
        menu.exec(self.tree.viewport().mapToGlobal(pos))


class DetailColumn:
    def __init__(self, title, text, sort=None, align=LEFT, width=80, default=False):
        self.title, self.text, self.sort = title, text, sort
        self.align, self.width, self.default = align, width, default


DETAIL_COLUMNS = [
    DetailColumn("Name", lambda p: p.name, width=150, default=True),
    DetailColumn("PID", lambda p: str(p.pid), lambda p: p.pid, RIGHT, 55, True),
    DetailColumn("Status", lambda p: p.status, width=75, default=True),
    DetailColumn("User name", lambda p: p.username, width=85, default=True),
    DetailColumn("CPU", lambda p: "{:02.0f}".format(min(99, p.cpu)), lambda p: p.cpu, RIGHT, 40, True),
    DetailColumn("Memory (private working set)", lambda p: fmt_kb(p.mem_private), lambda p: p.mem_private,
                 RIGHT, 110, True),
    DetailColumn("Description", lambda p: p.description, width=260, default=True),
    DetailColumn("Parent PID", lambda p: str(p.ppid), lambda p: p.ppid, RIGHT, 70),
    DetailColumn("CPU time", lambda p: fmt_cpu_time(p.cpu_time), lambda p: p.cpu_time, RIGHT, 70),
    DetailColumn("Working set (memory)", lambda p: fmt_kb(p.mem_rss), lambda p: p.mem_rss, RIGHT, 100),
    DetailColumn("Threads", lambda p: str(p.threads), lambda p: p.threads, RIGHT, 60),
    DetailColumn("Base priority", lambda p: actions.priority_name(p.nice), lambda p: -p.nice, LEFT, 85),
    DetailColumn("I/O read bytes", lambda p: "{:,}".format(p.io_read), lambda p: p.io_read, RIGHT, 100),
    DetailColumn("I/O write bytes", lambda p: "{:,}".format(p.io_write), lambda p: p.io_write, RIGHT, 100),
    DetailColumn("Image path name", lambda p: p.exe, width=220),
    DetailColumn("Command line", lambda p: p.cmdline, width=300),
]

WIN10_DETAIL_COLUMNS = [
    DetailColumn("Architecture", architecture, width=80, default=True),
    DetailColumn("Elevated", lambda p: "Yes" if p.euid == 0 else "No", width=65),
    DetailColumn("GPU", lambda p: "{:02.0f}".format(min(99, p.gpu)), lambda p: p.gpu, RIGHT, 40),
    DetailColumn("GPU engine", lambda p: p.gpu_engine if p.gpu >= 0.05 else "", width=110),
    DetailColumn("Dedicated GPU memory", lambda p: fmt_kb(p.gpu_dedicated), lambda p: p.gpu_dedicated,
                 RIGHT, 120),
    DetailColumn("Shared GPU memory", lambda p: fmt_kb(p.gpu_shared), lambda p: p.gpu_shared, RIGHT, 110),
]


TUX_DETAIL_COLUMNS = [DetailColumn(title, text, sort, align, width, default)
                      for title, text, sort, align, width, default in tuxui.PROC_COLUMNS
                      if title not in ("Parent PID", "State")]


class DetailsTab(TreeTab):
    goto_service = Signal(int)

    def __init__(self, win10=False, tux=False, parent=None):
        super().__init__(parent)
        self.columns = DETAIL_COLUMNS + (WIN10_DETAIL_COLUMNS if win10 else []) + \
            (TUX_DETAIL_COLUMNS if tux else [])
        if tux:
            # the Status column shows the real kernel state (Sleeping, Disk sleep, Zombie, ...)
            self.columns = [DetailColumn("Status", lambda p: tuxui.proc_status(p, p.status), width=85, default=True)
                            if c.title == "Status" else c for c in self.columns]
        self.settings_key = "{}/detail_columns{}".format("win10" if win10 else "win8", "_tux" if tux else "")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        titles = [c.title for c in self.columns]
        self.tree = make_tree(titles)
        self.header = install_header(self.tree, right_aligned=[i for i, c in enumerate(self.columns)
                                                               if c.align == RIGHT])
        self.tree.setHeaderLabels(titles)
        self.header.setFixedHeight(26)
        settings = QtCore.QSettings()
        visible = settings.value(self.settings_key, None, type=list) or \
            [c.title for c in self.columns if c.default]
        for idx, col in enumerate(self.columns):
            self.header.resizeSection(idx, col.width)
            self.header.setSectionHidden(idx, col.title not in visible)
        self.header.customContextMenuRequested.connect(self._header_menu)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemSelectionChanged.connect(self._sel_changed)
        layout.addWidget(self.tree, 1)
        self.end_btn = QtWidgets.QPushButton("End task")
        self.end_btn.clicked.connect(self.end_task)
        self.end_btn.setEnabled(False)
        self.fewer = LinkButton("Fewer details", Qt.ArrowType.UpArrow)
        layout.addWidget(bottom_bar([self.fewer], [self.end_btn]))
        self.service_pids = {}

    def _header_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        menu.addAction("Hide column", lambda: self.header.setSectionHidden(self.header.logicalIndexAt(pos), True)) \
            .setEnabled(self.header.logicalIndexAt(pos) > 0)
        menu.addAction("Select columns", self.choose_columns)
        menu.exec(self.header.mapToGlobal(pos))

    def choose_columns(self):
        titles = [c.title for c in self.columns[1:]]
        visible = [c.title for i, c in enumerate(self.columns) if not self.header.isSectionHidden(i)]
        dlg = ColumnChooser("Select columns", "Select the columns that will appear in the table.",
                            titles, visible, self)
        if dlg.exec():
            chosen = set(dlg.chosen())
            for idx, col in enumerate(self.columns[1:], start=1):
                self.header.setSectionHidden(idx, col.title not in chosen)
            QtCore.QSettings().setValue(self.settings_key, ["Name"] + sorted(chosen))

    def update_snapshot(self, snap):
        self.snap = snap
        with bulk_update(self.tree):
            self.begin()
            for proc in snap.procs.values():
                item = self.node(proc.pid)
                for idx, col in enumerate(self.columns):
                    set_cell(item, idx, col.text(proc), col.sort(proc) if col.sort else None, col.align)
                if item.icon(0).isNull():
                    item.setIcon(0, icon_for(proc.icon, SYS_ICON if proc.kind == KIND_SYSTEM else PROC_ICON))
            self.end()
        self._sel_changed()

    def current_proc(self):
        key = self.current_key()
        return self.snap.procs.get(key) if self.snap and key is not None else None

    def _sel_changed(self):
        self.end_btn.setEnabled(self.current_proc() is not None)

    def end_task(self):
        proc = self.current_proc()
        if proc is not None and confirm_end(self, proc.name, win8=True):
            guarded(self, "Unable to terminate process", actions.end_process, proc.pid)

    def select_pid(self, pid):
        item = self.items.get(pid)
        if item is not None:
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)
            self.tree.setFocus()

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None or self.snap is None:
            return
        proc = self.snap.procs.get(item.data(0, KEY_ROLE))
        if proc is None:
            return
        menu = process_menu(self, proc, win8=True)
        menu.addAction("Search online", lambda: search_online(self, proc.name))
        goto = menu.addAction("Go to service(s)", lambda: self.goto_service.emit(proc.pid))
        goto.setEnabled(proc.pid in self.service_pids)
        menu.exec(self.tree.viewport().mapToGlobal(pos))
