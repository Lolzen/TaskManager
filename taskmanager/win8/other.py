"""Windows 8 *App history* and *Startup* tabs and the *Fewer details* view."""

import datetime
import os

from ..backend import actions, startup
from ..backend.formatting import fmt_bytes, fmt_cpu_time
from ..core import bulk_update, run_async
from ..qt import QtCore, QtWidgets, Qt, Signal
from ..widgets.dialogs import RunDialog, guarded, show_error
from ..widgets.tree import ItemSync, KEY_ROLE, RIGHT, make_tree, set_cell
from .common import APP_ICON, LinkButton, bottom_bar, icon_for, install_header
from .processes import search_online


class AppHistoryTab(QtWidgets.QWidget):
    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.setObjectName("win8page")
        self.history = history
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(10, 8, 10, 6)
        self.since = QtWidgets.QLabel()
        top.addWidget(self.since)
        clear = LinkButton("Delete usage history")
        clear.clicked.connect(self._clear)
        top.addWidget(clear)
        top.addStretch(1)
        layout.addLayout(top)
        cols = ["Name", "CPU time", "Disk read", "Disk write", "Total disk I/O"]
        self.tree = make_tree(cols)
        self.header = install_header(self.tree, right_aligned=[1, 2, 3, 4])
        self.tree.setHeaderLabels(cols)
        for idx, width in enumerate((250, 90, 90, 90, 100)):
            self.header.resizeSection(idx, width)
        self.tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self.sync = ItemSync(self.tree)
        layout.addWidget(self.tree, 1)
        self.fewer = LinkButton("Fewer details", Qt.ArrowType.UpArrow)
        layout.addWidget(bottom_bar([self.fewer], []))
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start(5000)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.timer.stop()

    def _clear(self):
        self.history.clear()
        self.refresh()

    def refresh(self):
        since = datetime.datetime.fromtimestamp(self.history.since).strftime("%x")
        self.since.setText("Resource usage since {} for current user account.".format(since))
        total_cpu = sum(a["cpu"] for a in self.history.apps.values())
        total_io = sum(a["read"] + a["write"] for a in self.history.apps.values())
        self.header.set_metric(1, fmt_cpu_time(total_cpu), None)
        self.header.set_metric(4, fmt_bytes(total_io), None)
        with bulk_update(self.tree):
            self.sync.begin()
            for app_id, entry in self.history.apps.items():
                item = self.sync.get(app_id)
                set_cell(item, 0, entry["name"], entry["name"].lower())
                if item.icon(0).isNull():
                    item.setIcon(0, icon_for("", APP_ICON))
                set_cell(item, 1, fmt_cpu_time(entry["cpu"]), entry["cpu"], RIGHT)
                set_cell(item, 2, fmt_bytes(entry["read"]), entry["read"], RIGHT)
                set_cell(item, 3, fmt_bytes(entry["write"]), entry["write"], RIGHT)
                io = entry["read"] + entry["write"]
                set_cell(item, 4, fmt_bytes(io), io, RIGHT)
            self.sync.end()


class StartupTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("win8page")
        self.entries = {}
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        cols = ["Name", "Publisher", "Status", "Startup impact", "Command"]
        self.tree = make_tree(cols)
        self.header = install_header(self.tree)
        self.tree.setHeaderLabels(cols)
        self.header.setFixedHeight(26)
        for idx, width in enumerate((230, 150, 80, 100, 250)):
            self.header.resizeSection(idx, width)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemSelectionChanged.connect(self._sel_changed)
        self.sync = ItemSync(self.tree)
        layout.addWidget(self.tree, 1)
        self.button = QtWidgets.QPushButton("Disable")
        self.button.setEnabled(False)
        self.button.clicked.connect(self.toggle)
        self.fewer = LinkButton("Fewer details", Qt.ArrowType.UpArrow)
        layout.addWidget(bottom_bar([self.fewer], [self.button]))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        run_async(startup.list_startup, self._loaded)

    def _loaded(self, items, error):
        if error is not None:
            show_error(self, "Startup", error)
            return
        self.entries = {i.id: i for i in items}
        with bulk_update(self.tree):
            self.sync.begin()
            for entry in items:
                item = self.sync.get(entry.id)
                set_cell(item, 0, entry.name, entry.name.lower())
                if item.icon(0).isNull():
                    item.setIcon(0, icon_for("", APP_ICON))
                set_cell(item, 1, entry.publisher)
                set_cell(item, 2, entry.status)
                set_cell(item, 3, entry.impact)
                set_cell(item, 4, entry.command)
            self.sync.end()
        self._sel_changed()

    def _current(self):
        items = self.tree.selectedItems()
        return self.entries.get(items[0].data(0, KEY_ROLE)) if items else None

    def _sel_changed(self):
        entry = self._current()
        self.button.setEnabled(entry is not None and entry.editable)
        self.button.setText("Enable" if entry is not None and not entry.enabled else "Disable")

    def toggle(self):
        entry = self._current()
        if entry is None:
            return
        if guarded(self, "Startup", startup.set_enabled, entry, not entry.enabled):
            self.refresh()

    def _menu(self, pos):
        entry = self._current()
        if entry is None:
            return
        menu = QtWidgets.QMenu(self)
        act = menu.addAction("Enable" if not entry.enabled else "Disable", self.toggle)
        act.setEnabled(entry.editable)
        menu.addSeparator()
        menu.addAction("Open file location", lambda: guarded(self, "Open file location", actions.open_path,
                                                             os.path.dirname(entry.path)))
        menu.addAction("Search online", lambda: search_online(self, entry.name))
        menu.addAction("Properties", lambda: guarded(self, "Properties", actions.open_path, entry.path))
        menu.exec(self.tree.viewport().mapToGlobal(pos))


class CompactView(QtWidgets.QWidget):
    """The *Fewer details* view: just the running apps and an End task button."""

    more = Signal()
    used = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("win8page")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("compact")
        self.list.setIconSize(QtCore.QSize(16, 16))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemDoubleClicked.connect(lambda *_: self.switch_to())
        self.list.itemSelectionChanged.connect(self._sel_changed)
        layout.addWidget(self.list, 1)
        more = LinkButton("More details", Qt.ArrowType.DownArrow)
        more.clicked.connect(self.more.emit)
        self.end_btn = QtWidgets.QPushButton("End task")
        self.end_btn.setEnabled(False)
        self.end_btn.clicked.connect(self.end_task)
        layout.addWidget(bottom_bar([more], [self.end_btn]))
        self.apps = {}
        self.windows = None
        self._tick = 0

    def update_snapshot(self, snap):
        apps = {}
        for proc in snap.procs.values():
            if proc.kind == "app" and proc.app_id:
                apps.setdefault(proc.app_id, []).append(proc)
        if self._tick % 2 == 0:
            self.windows = actions.list_windows()
        self._tick += 1
        self.apps = apps
        current = {self.list.item(i).data(Qt.ItemDataRole.UserRole): self.list.item(i)
                   for i in range(self.list.count())}
        for app_id, procs in sorted(apps.items(), key=lambda kv: kv[1][0].app_name.lower()):
            item = current.pop(app_id, None)
            hung = any(p.status == "Suspended" for p in procs)
            text = procs[0].app_name + ("  (Not responding)" if hung else "")
            if item is None:
                item = QtWidgets.QListWidgetItem(icon_for(procs[0].icon, APP_ICON), text)
                item.setData(Qt.ItemDataRole.UserRole, app_id)
                self.list.addItem(item)
            elif item.text() != text:
                item.setText(text)
        for item in current.values():
            self.list.takeItem(self.list.row(item))
        self.list.sortItems()

    def _current(self):
        items = self.list.selectedItems()
        return self.apps.get(items[0].data(Qt.ItemDataRole.UserRole), []) if items else []

    def _sel_changed(self):
        self.end_btn.setEnabled(bool(self._current()))

    def end_task(self):
        for proc in self._current():
            if not guarded(self, "Unable to end task", actions.end_process, proc.pid):
                break

    def _window_for(self, procs):
        pids = {p.pid for p in procs}
        return next((w for w in (self.windows or []) if w[1] in pids), None)

    def switch_to(self):
        window = self._window_for(self._current())
        if window is not None:
            actions.activate_window(window[0])
            self.used.emit()

    def _menu(self, pos):
        procs = self._current()
        if not procs:
            return
        proc = procs[0]
        menu = QtWidgets.QMenu(self)
        menu.addAction("Switch to", self.switch_to).setEnabled(self._window_for(procs) is not None)
        menu.addAction("End task", self.end_task)
        menu.addSeparator()
        menu.addAction("Run new task", lambda: RunDialog(self, win8=True).exec())
        menu.addSeparator()
        menu.addAction("Open file location", lambda: guarded(self, "Open file location",
                                                             actions.open_file_location, proc.exe))
        menu.addAction("Search online", lambda: search_online(self, proc.app_name))
        from ..widgets.dialogs import PropertiesDialog
        menu.addAction("Properties", lambda: PropertiesDialog(proc, self).exec())
        menu.exec(self.list.viewport().mapToGlobal(pos))
