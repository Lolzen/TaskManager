"""Windows 8 *Processes*, *Users* and *Details* tabs."""

import os
import socket
from urllib.parse import quote_plus

from ..backend import actions
from ..backend.formatting import MB, fmt_cpu_time, fmt_disk_rate, fmt_kb, fmt_mem_mb
from ..backend.sampler import KIND_APP, KIND_BACKGROUND, KIND_SYSTEM
from ..core import bulk_update
from ..qt import QtCore, QtWidgets, Qt, Signal
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


PROC_COLUMNS = ["Name", "Type", "Status", "PID", "Process name", "Command line", "CPU", "Memory", "Disk", "Network"]
PROC_HIDDEN = ["Type", "PID", "Process name", "Command line"]
TYPE_LABELS = {KIND_APP: "App", KIND_BACKGROUND: "Background process", KIND_SYSTEM: "System process"}


class ProcessesTab(MetricTreeTab):
    METRIC_COLS = (6, 7, 8, 9)
    goto_details = Signal(int)
    used = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.group_by_type = True
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.tree = make_tree(PROC_COLUMNS, root_decorated=True)
        self.header = install_header(self.tree, right_aligned=[3, 6, 7, 8, 9])
        self.tree.setHeaderLabels(PROC_COLUMNS)
        for idx, width in enumerate((250, 120, 80, 55, 110, 250, 70, 85, 75, 75)):
            self.header.resizeSection(idx, width)
        for title in PROC_HIDDEN:
            self.header.setSectionHidden(PROC_COLUMNS.index(title), True)
        column_menu(self.tree, PROC_COLUMNS)
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
                self.fill_metrics(item, sum(p.cpu for p in procs), sum(p.mem_private for p in procs),
                                  sum(p.disk_bps for p in procs), total)
                if len(procs) > 1:
                    for proc in procs:
                        child = self.node("pid:{}".format(proc.pid), item)
                        self._fill_proc(child, proc, total)

            for kind in (KIND_BACKGROUND, KIND_SYSTEM, KIND_APP):
                for proc in singles[kind]:
                    item = self.node("pid:{}".format(proc.pid), parents.get(kind))
                    self._fill_proc(item, proc, total)
            self.end()
        self.update_header(snap)
        self._sel_changed()

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
        self.fill_metrics(item, proc.cpu, proc.mem_private, proc.disk_bps, total)

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.own_user = None
        try:
            import pwd
            self.own_user = pwd.getpwuid(os.getuid()).pw_name
        except (ImportError, KeyError):
            self.own_user = os.environ.get("USER", "")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.tree = make_tree(USER_COLUMNS, root_decorated=True)
        self.header = install_header(self.tree, right_aligned=[1, 5, 6, 7, 8])
        self.tree.setHeaderLabels(USER_COLUMNS)
        for idx, width in enumerate((230, 40, 80, 110, 90, 70, 85, 75, 75)):
            self.header.resizeSection(idx, width)
        for idx in (1, 2, 3):
            self.header.setSectionHidden(idx, True)
        column_menu(self.tree, USER_COLUMNS, always=("User",))
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
                set_cell(item, 0, "{} ({})".format(name, len(procs)), name.lower())
                if item.icon(0).isNull():
                    item.setIcon(0, icon_for("user-identity", USER_ICON))
                set_cell(item, 1, str(sid), sid, RIGHT)
                set_cell(item, 2, (session.terminal if session else "") or "Console")
                set_cell(item, 3, (session.host if session else "") or socket.gethostname())
                set_cell(item, 4, "")
                self.fill_metrics(item, sum(p.cpu for p in procs), sum(p.mem_private for p in procs),
                                  sum(p.disk_bps for p in procs), total)
                for proc in procs:
                    child = self.node("pid:{}".format(proc.pid), item)
                    label = proc.app_name or proc.name
                    set_cell(child, 0, label, label.lower())
                    if child.icon(0).isNull():
                        child.setIcon(0, icon_for(proc.icon, APP_ICON if proc.app_id else PROC_ICON))
                    set_cell(child, 4, "Suspended" if proc.status == "Suspended" else "")
                    self.fill_metrics(child, proc.cpu, proc.mem_private, proc.disk_bps, total)
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


class DetailsTab(TreeTab):
    goto_service = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        titles = [c.title for c in DETAIL_COLUMNS]
        self.tree = make_tree(titles)
        self.header = install_header(self.tree, right_aligned=[i for i, c in enumerate(DETAIL_COLUMNS)
                                                               if c.align == RIGHT])
        self.tree.setHeaderLabels(titles)
        self.header.setFixedHeight(26)
        settings = QtCore.QSettings()
        visible = settings.value("win8/detail_columns", None, type=list) or \
            [c.title for c in DETAIL_COLUMNS if c.default]
        for idx, col in enumerate(DETAIL_COLUMNS):
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
        titles = [c.title for c in DETAIL_COLUMNS[1:]]
        visible = [c.title for i, c in enumerate(DETAIL_COLUMNS) if not self.header.isSectionHidden(i)]
        dlg = ColumnChooser("Select columns", "Select the columns that will appear in the table.",
                            titles, visible, self)
        if dlg.exec():
            chosen = set(dlg.chosen())
            for idx, col in enumerate(DETAIL_COLUMNS[1:], start=1):
                self.header.setSectionHidden(idx, col.title not in chosen)
            QtCore.QSettings().setValue("win8/detail_columns", ["Name"] + sorted(chosen))

    def update_snapshot(self, snap):
        self.snap = snap
        with bulk_update(self.tree):
            self.begin()
            for proc in snap.procs.values():
                item = self.node(proc.pid)
                for idx, col in enumerate(DETAIL_COLUMNS):
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
