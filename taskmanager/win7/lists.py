"""Windows 7 *Applications*, *Processes* and *Users* tabs."""

import datetime
import os
import socket

from ..backend import actions
from ..backend.formatting import fmt_cpu_time, fmt_kb
from ..core import bulk_update
from ..qt import QtCore, QtWidgets, Qt, Signal
from ..widgets.dialogs import RunDialog, confirm, guarded, process_menu
from ..widgets.tree import (KEY_ROLE, LEFT, RIGHT, ColumnChooser, ItemSync, make_tree,
                            selected_key, set_cell)


def _buttons(*specs):
    row = QtWidgets.QHBoxLayout()
    row.addStretch(1)
    buttons = []
    for text in specs:
        button = QtWidgets.QPushButton(text)
        button.setMinimumWidth(90)
        row.addWidget(button)
        buttons.append(button)
    return row, buttons


class ApplicationsTab(QtWidgets.QWidget):
    goto_pid = Signal(int)
    used = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.tree = make_tree(["Task", "Status"])
        self.tree.header().resizeSection(0, 280)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemDoubleClicked.connect(lambda *_: self.switch_to())
        self.sync = ItemSync(self.tree)
        layout.addWidget(self.tree, 1)
        row, (self.end_btn, self.switch_btn, self.new_btn) = _buttons("&End Task", "&Switch To", "&New Task...")
        self.end_btn.clicked.connect(self.end_task)
        self.switch_btn.clicked.connect(self.switch_to)
        self.new_btn.clicked.connect(lambda: RunDialog(self).exec())
        layout.addLayout(row)
        self.tasks = {}  # key -> (window_id or None, [pids], title)
        self._snap = None
        self._windows = None
        self._win_timer = 0

    def update_snapshot(self, snap):
        self._snap = snap
        # wmctrl is cheap but not free: refresh the window list every 2 samples
        if self._win_timer % 2 == 0:
            self._windows = actions.list_windows()
        self._win_timer += 1
        tasks = {}
        if self._windows is not None:
            for wid, pid, title in self._windows:
                tasks["win:" + wid] = (wid, [pid], title or "(untitled)")
        else:
            for proc in snap.procs.values():
                if proc.kind == "app" and proc.app_id:
                    entry = tasks.setdefault("app:" + proc.app_id, (None, [], proc.app_name))
                    entry[1].append(proc.pid)
        self.tasks = tasks
        with bulk_update(self.tree):
            self.sync.begin()
            for key, (_wid, pids, title) in tasks.items():
                item = self.sync.get(key)
                hung = any(snap.procs.get(pid) and snap.procs[pid].status == "Suspended" for pid in pids)
                set_cell(item, 0, title)
                set_cell(item, 1, "Not Responding" if hung else "Running")
            self.sync.end()
        has_sel = selected_key(self.tree) is not None
        self.end_btn.setEnabled(has_sel)
        self.switch_btn.setEnabled(has_sel)

    def _current(self):
        key = selected_key(self.tree)
        return self.tasks.get(key) if key else None

    def end_task(self):
        task = self._current()
        if task is None:
            return
        wid, pids, _title = task
        if wid is not None:
            actions.close_window(wid)
            return
        for pid in pids:
            guarded(self, "End Task", actions.end_process, pid)

    def switch_to(self):
        task = self._current()
        if task and task[0]:
            actions.activate_window(task[0])
            self.used.emit()

    def _menu(self, pos):
        task = self._current()
        if task is None:
            return
        menu = QtWidgets.QMenu(self)
        menu.addAction("&Switch To", self.switch_to).setEnabled(bool(task[0]))
        menu.addSeparator()
        menu.addAction("&End Task", self.end_task)
        menu.addSeparator()
        menu.addAction("&Go To Process", lambda: self.goto_pid.emit(task[1][0]))
        menu.exec(self.tree.viewport().mapToGlobal(pos))


class Column:
    def __init__(self, title, text, sort=None, align=LEFT, width=80, default=False):
        self.title, self.text, self.sort = title, text, sort
        self.align, self.width, self.default = align, width, default


PROCESS_COLUMNS = [
    Column("Image Name", lambda p, s: p.name, width=130, default=True),
    Column("PID (Process Identifier)", lambda p, s: str(p.pid), lambda p: p.pid, RIGHT, 50),
    Column("User Name", lambda p, s: s.user_text(p), width=80, default=True),
    Column("CPU", lambda p, s: "{:02.0f}".format(min(99, p.cpu)), lambda p: p.cpu, RIGHT, 40, True),
    Column("CPU Time", lambda p, s: fmt_cpu_time(p.cpu_time), lambda p: p.cpu_time, RIGHT, 70),
    Column("Memory - Working Set", lambda p, s: fmt_kb(p.mem_rss), lambda p: p.mem_rss, RIGHT, 110),
    Column("Memory (Private Working Set)", lambda p, s: fmt_kb(p.mem_private), lambda p: p.mem_private,
           RIGHT, 150, True),
    Column("Threads", lambda p, s: str(p.threads), lambda p: p.threads, RIGHT, 55),
    Column("Base Priority", lambda p, s: actions.priority_name(p.nice), lambda p: -p.nice, LEFT, 85),
    Column("I/O Reads (bytes)", lambda p, s: "{:,}".format(p.io_read), lambda p: p.io_read, RIGHT, 100),
    Column("I/O Writes (bytes)", lambda p, s: "{:,}".format(p.io_write), lambda p: p.io_write, RIGHT, 100),
    Column("Image Path Name", lambda p, s: p.exe, width=200),
    Column("Command Line", lambda p, s: p.cmdline, width=250),
    Column("Description", lambda p, s: p.description, width=200, default=True),
]


class ProcessesTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QtCore.QSettings()
        saved = self.settings.value("win7/columns", None, type=list)
        self.visible = saved or [c.title for c in PROCESS_COLUMNS if c.default]
        self.full_account = False
        self.own_uid = os.getuid() if hasattr(os, "getuid") else -1
        self.host = socket.gethostname().split(".")[0].upper()
        self.snap = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.tree = None
        self.tree_holder = QtWidgets.QVBoxLayout()
        layout.addLayout(self.tree_holder, 1)
        bottom = QtWidgets.QHBoxLayout()
        self.all_users = QtWidgets.QCheckBox("Show processes from all users")
        self.all_users.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_VistaShield))
        self.all_users.setChecked(self.settings.value("win7/all_users", False, type=bool))
        self.all_users.toggled.connect(self._all_users_toggled)
        bottom.addWidget(self.all_users)
        bottom.addStretch(1)
        self.end_btn = QtWidgets.QPushButton("&End Process")
        self.end_btn.setMinimumWidth(90)
        self.end_btn.clicked.connect(self.end_process)
        bottom.addWidget(self.end_btn)
        layout.addLayout(bottom)
        self._build_tree()

    def user_text(self, proc):
        if self.full_account:
            return "{}\\{}".format(self.host, proc.username)
        return proc.username

    def _columns(self):
        return [c for c in PROCESS_COLUMNS if c.title in self.visible]

    def _build_tree(self):
        sort_col, order = 3, Qt.SortOrder.DescendingOrder
        if self.tree is not None:
            sort_col, order = self.tree.sortColumn(), self.tree.header().sortIndicatorOrder()
            self.tree.setParent(None)
            self.tree.deleteLater()
        cols = self._columns()
        self.tree = make_tree([c.title for c in cols])
        for idx, col in enumerate(cols):
            self.tree.header().resizeSection(idx, col.width)
        self.tree.sortByColumn(min(sort_col, len(cols) - 1), order)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemSelectionChanged.connect(self._sel_changed)
        self.sync = ItemSync(self.tree)
        self.tree_holder.addWidget(self.tree)
        if self.snap is not None:
            self.update_snapshot(self.snap)

    def choose_columns(self):
        titles = [c.title for c in PROCESS_COLUMNS if c.title != "Image Name"]
        dlg = ColumnChooser("Select Process Page Columns",
                            "Select the columns that will appear on the Process page of the Task Manager.",
                            titles, self.visible, self)
        if dlg.exec():
            self.visible = ["Image Name"] + dlg.chosen()
            self.settings.setValue("win7/columns", self.visible)
            self._build_tree()

    def _all_users_toggled(self, checked):
        self.settings.setValue("win7/all_users", checked)
        if self.snap is not None:
            self.update_snapshot(self.snap)

    def update_snapshot(self, snap):
        self.snap = snap
        cols = self._columns()
        show_all = self.all_users.isChecked()
        with bulk_update(self.tree):
            self.sync.begin()
            for proc in snap.procs.values():
                if not show_all and proc.uid != self.own_uid:
                    continue
                item = self.sync.get(proc.pid)
                for idx, col in enumerate(cols):
                    set_cell(item, idx, col.text(proc, self), col.sort(proc) if col.sort else None, col.align)
            self.sync.end()
        self._sel_changed()

    def _sel_changed(self):
        self.end_btn.setEnabled(selected_key(self.tree) is not None)

    def current_proc(self):
        pid = selected_key(self.tree)
        return self.snap.procs.get(pid) if self.snap and pid is not None else None

    def end_process(self):
        proc = self.current_proc()
        if proc is None:
            return
        from ..widgets.dialogs import confirm_end
        if confirm_end(self, proc.name):
            guarded(self, "Unable to Terminate Process", actions.end_process, proc.pid)

    def select_pid(self, pid):
        item = self.sync.items.get(pid)
        if item is None and not self.all_users.isChecked():
            self.all_users.setChecked(True)
            item = self.sync.items.get(pid)
        if item is not None:
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)
            self.tree.setFocus()

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        proc = self.snap.procs.get(item.data(0, KEY_ROLE))
        if proc is None:
            return
        menu = process_menu(self, proc)
        menu.exec(self.tree.viewport().mapToGlobal(pos))


class UsersTab(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.tree = make_tree(["User", "ID", "Status", "Client Name", "Session", "Logon Time"])
        for col, width in enumerate((110, 40, 70, 110, 80, 140)):
            self.tree.header().resizeSection(col, width)
        self.tree.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        self.sync = ItemSync(self.tree)
        layout.addWidget(self.tree, 1)
        row, (self.disc_btn, self.logoff_btn, self.msg_btn) = _buttons("&Disconnect", "&Logoff", "Send &Message...")
        self.disc_btn.clicked.connect(self.logoff)
        self.logoff_btn.clicked.connect(self.logoff)
        self.msg_btn.clicked.connect(self.send_message)
        layout.addLayout(row)
        self.users = {}

    def update_snapshot(self, snap):
        self.users = {}
        self.sync.begin()
        for idx, user in enumerate(snap.users):
            key = "{}:{}:{}".format(user.name, user.terminal, user.started)
            self.users[key] = user
            item = self.sync.get(key)
            set_cell(item, 0, user.name)
            set_cell(item, 1, str(idx), idx, RIGHT)
            set_cell(item, 2, "Active")
            set_cell(item, 3, user.host or "")
            set_cell(item, 4, "Console" if (user.terminal or "").startswith(("tty", "seat", ":")) else (user.terminal or ""))
            set_cell(item, 5, datetime.datetime.fromtimestamp(user.started).strftime("%Y-%m-%d %H:%M"), user.started)
        self.sync.end()

    def _current(self):
        key = selected_key(self.tree)
        return self.users.get(key) if key else None

    def logoff(self):
        user = self._current()
        if user is None:
            return
        if confirm(self, "Windows Task Manager", "Are you sure you want to log off the selected user?",
                   "Any unsaved data belonging to {} may be lost.".format(user.name), "Log off user"):
            guarded(self, "Log off", actions.logoff_session, user)

    def send_message(self):
        user = self._current()
        if user is None:
            return
        text, ok = QtWidgets.QInputDialog.getMultiLineText(self, "Send Message", "Message:")
        if ok and text.strip():
            guarded(self, "Send Message", actions.send_message, user, text)
