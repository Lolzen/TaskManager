"""The *Services* tab; identical columns in Windows 7 and Windows 8."""

import shutil
import subprocess

from ..backend import services as svc_backend
from ..core import bulk_update, run_async
from ..qt import QtCore, QtWidgets, Qt, Signal
from .dialogs import show_error
from .tree import ItemSync, LEFT, RIGHT, make_tree, set_cell

SERVICE_TOOLS = [["systemd-manager"], ["gnome-system-tools"], ["systemadm"], ["cockpit-desktop", "/system/services"]]


class ServicesPanel(QtWidgets.QWidget):
    goto_pid = Signal(int)

    def __init__(self, win8=False, parent=None):
        super().__init__(parent)
        self.win8 = win8
        self.services = []
        self._loading = False
        layout = QtWidgets.QVBoxLayout(self)
        margin = 0 if win8 else 6
        layout.setContentsMargins(margin, margin, margin, margin)
        self.tree = make_tree(["Name", "PID", "Description", "Status", "Group"])
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.customContextMenuRequested.connect(self._menu)
        header = self.tree.header()
        for col, width in enumerate((150, 55, 260, 70, 120)):
            header.resizeSection(col, width)
        self.sync = ItemSync(self.tree)
        layout.addWidget(self.tree, 1)
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        self.message.hide()
        layout.addWidget(self.message)

        bottom = QtWidgets.QHBoxLayout()
        if win8:
            bottom.setContentsMargins(10, 6, 10, 8)
            link = QtWidgets.QLabel('<a href="#">Open Services</a>')
            link.setObjectName("win8link")
            link.linkActivated.connect(self._open_tool)
            bottom.addWidget(link)
            bottom.addStretch(1)
        else:
            bottom.addStretch(1)
            button = QtWidgets.QPushButton("&Services...")
            button.clicked.connect(self._open_tool)
            bottom.addWidget(button)
        layout.addLayout(bottom)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.setInterval(5000)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.timer.stop()

    def refresh(self):
        if self._loading:
            return
        self._loading = True
        run_async(svc_backend.list_services, self._loaded)

    def _loaded(self, result, error):
        self._loading = False
        if error is not None:
            self.message.setText(str(error))
            self.message.show()
            return
        self.message.hide()
        self.services = result
        with bulk_update(self.tree):
            self.sync.begin()
            for svc in result:
                item = self.sync.get(svc.name)
                set_cell(item, 0, svc.name)
                set_cell(item, 1, str(svc.pid) if svc.pid else "", svc.pid, RIGHT)
                set_cell(item, 2, svc.description)
                set_cell(item, 3, svc.status, None, LEFT)
                set_cell(item, 4, svc.group)
                item.setToolTip(3, "{} — {}".format(svc.detail, svc.startup) if svc.startup else svc.detail)
            self.sync.end()

    def _service(self, item):
        name = item.data(0, Qt.ItemDataRole.UserRole + 2)
        return next((s for s in self.services if s.name == name), None)

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        svc = self._service(item)
        if svc is None:
            return
        menu = QtWidgets.QMenu(self)
        running = svc.status == "Running"
        start = menu.addAction("Start" if self.win8 else "Start Service", lambda: self._control(svc, "start"))
        stop = menu.addAction("Stop" if self.win8 else "Stop Service", lambda: self._control(svc, "stop"))
        start.setEnabled(not running)
        stop.setEnabled(running)
        if self.win8:
            restart = menu.addAction("Restart", lambda: self._control(svc, "restart"))
            restart.setEnabled(running)
            menu.addSeparator()
            menu.addAction("Open Services", self._open_tool)
            menu.addAction("Search online", lambda: self._search(svc))
            menu.addSeparator()
        goto = menu.addAction("Go to details" if self.win8 else "Go to Process", lambda: self.goto_pid.emit(svc.pid))
        goto.setEnabled(bool(svc.pid))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _control(self, svc, action):
        def done(_result, error):
            if error is not None:
                show_error(self, "Services", error)
            self.refresh()

        run_async(lambda: svc_backend.control(svc, action), done)

    def _search(self, svc):
        from ..backend.actions import open_path
        try:
            open_path("https://duckduckgo.com/?q={}+service".format(QtCore.QUrl.toPercentEncoding(svc.name)
                                                                  .data().decode()))
        except OSError as exc:
            show_error(self, "Search online", exc)

    def _open_tool(self, *_args):
        for cmd in SERVICE_TOOLS:
            if shutil.which(cmd[0]):
                subprocess.Popen(cmd, start_new_session=True)
                return
        self.refresh()

    def select_pid(self, pid):
        for item in self.sync.items.values():
            if item.text(1) == str(pid):
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return True
        return False
