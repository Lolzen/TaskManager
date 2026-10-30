"""Windows 8 Task Manager layout."""

from ..backend import services as svc_backend
from ..core import run_async
from ..qt import QtCore, QtGui, QtWidgets
from ..widgets.dialogs import AboutDialog, RunDialog
from ..widgets.services import ServicesPanel
from ..widgets.tux import TuxPanel, tux_title
from .common import STYLE
from .other import AppHistoryTab, CompactView, StartupTab
from .performance import PerformanceTab
from .processes import DetailsTab, ProcessesTab, UsersTab


class Win8Window(QtWidgets.QMainWindow):
    LAYOUT = "win8"
    WIN10 = False
    STYLE = STYLE
    DEFAULT_SIZE = QtCore.QSize(700, 640)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setObjectName("win8")
        self.tux = controller.tux
        self.setWindowTitle(tux_title("Task Manager") if self.tux else "Task Manager")
        self.setStyleSheet(self.STYLE)
        self.settings = QtCore.QSettings()
        key = self.LAYOUT

        self.stack = QtWidgets.QStackedWidget()
        self.compact_view = CompactView()
        self.compact_view.more.connect(lambda: self.set_compact(False))
        self.compact_view.used.connect(controller.used_window)
        self.stack.addWidget(self.compact_view)

        self.tabs = QtWidgets.QTabWidget()
        self.procs = ProcessesTab(win10=self.WIN10, tux=self.tux)
        self.perf = PerformanceTab(win10=self.WIN10, tux=self.tux)
        self.history = AppHistoryTab(controller.history)
        self.startup = StartupTab(win10=self.WIN10, tux=self.tux)
        self.users = UsersTab(win10=self.WIN10, tux=self.tux)
        self.details = DetailsTab(win10=self.WIN10, tux=self.tux)
        self.services = ServicesPanel(win8=True, tux=self.tux)
        self.tux_panel = TuxPanel(win8=True) if self.tux else None
        self.services.setObjectName("win8page")
        for widget, title in ((self.procs, "Processes"), (self.perf, "Performance"),
                              (self.history, "App history"), (self.startup, "Startup"),
                              (self.users, "Users"), (self.details, "Details"), (self.services, "Services")):
            self.tabs.addTab(widget, title)
            fewer = getattr(widget, "fewer", None)
            if fewer is not None:
                fewer.clicked.connect(lambda: self.set_compact(True))
        if self.tux_panel is not None:
            self.tabs.addTab(self.tux_panel, "Tux")
        self.stack.addWidget(self.tabs)
        self.setCentralWidget(self.stack)

        self.procs.goto_details.connect(self.goto_details)
        self.procs.used.connect(controller.used_window)
        self.services.goto_pid.connect(self.goto_details)
        self.details.goto_service.connect(self.goto_service)
        self.perf.summary_toggled.connect(self._summary)

        self._build_menus()
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.setCurrentIndex(self.initial_tab())
        self.compact = None
        self.set_compact(self.settings.value(key + "/compact", False, type=bool))
        self._load_service_pids()

        if controller.sampler.last is not None:
            self.on_snapshot(controller.sampler.last)

    # -- menus ---------------------------------------------------------------------
    def _build_menus(self):
        mb = self.menuBar()
        c = self.controller
        file_menu = mb.addMenu("&File")
        file_menu.addAction("&Run new task", lambda: RunDialog(self, win8=True).exec())
        file_menu.addSeparator()
        file_menu.addAction("E&xit", c.quit)

        opts = mb.addMenu("&Options")
        for text, value, setter in (("&Always on top", c.always_on_top, c.set_always_on_top),
                                    ("&Minimize on use", c.minimize_on_use, c.set_minimize_on_use),
                                    ("&Hide when minimized", c.hide_when_minimized, c.set_hide_when_minimized)):
            act = opts.addAction(text, setter)
            act.setCheckable(True)
            act.setChecked(value)

        view = mb.addMenu("&View")
        view.addAction("&Refresh now", c.sampler.refresh_now).setShortcut(QtGui.QKeySequence("F5"))
        speed = view.addMenu("&Update speed")
        group = QtGui.QActionGroup(speed)
        for name in ("High", "Normal", "Low", "Paused"):
            act = speed.addAction("&" + name, lambda n=name: c.set_speed(n))
            act.setCheckable(True)
            act.setChecked(c.sampler.speed == name)
            group.addAction(act)
        view.addSeparator()
        self.act_group = view.addAction("&Group by type", self.procs.set_group_by_type)
        self.act_group.setCheckable(True)
        self.act_group.setChecked(True)
        self.act_expand = view.addAction("&Expand all", lambda: self.procs.tree.expandAll())
        self.act_collapse = view.addAction("&Collapse all", self._collapse_all)
        self.extend_menus(opts, view)
        view.addSeparator()
        c.add_layout_menu(view, self.LAYOUT)

        help_menu = mb.addMenu("&Help")
        help_menu.addAction("Task Manager &help", c.open_help)
        help_menu.addAction("&About Task Manager", lambda: AboutDialog(self, "Task Manager").exec())

    def initial_tab(self):
        return self.settings.value(self.LAYOUT + "/tab", 0, type=int)

    def extend_menus(self, options, view):
        """Hook for the Windows 10 layout's extra menu entries."""

    def _collapse_all(self):
        tree = self.procs.tree
        for i in range(tree.topLevelItemCount()):
            group = tree.topLevelItem(i)
            for j in range(group.childCount()):
                group.child(j).setExpanded(False)
            if not self.procs.group_by_type:
                group.setExpanded(False)

    def _tab_changed(self, index):
        widget = self.tabs.widget(index)
        for act in (self.act_group, self.act_expand, self.act_collapse):
            act.setEnabled(widget is self.procs)
        self.settings.setValue(self.LAYOUT + "/tab", index)
        snap = self.controller.sampler.last
        live = (self.procs, self.users, self.details) + ((self.startup,) if self.WIN10 else ()) + \
            ((self.tux_panel,) if self.tux_panel is not None else ())
        if snap is not None and widget in live:
            widget.update_snapshot(snap)

    # -- modes -------------------------------------------------------------------
    def set_compact(self, compact):
        if compact == self.compact:
            return
        key = self.LAYOUT
        if self.compact is not None:
            self.settings.setValue(key + ("/compact_size" if self.compact else "/size"), self.size())
        self.compact = compact
        self.settings.setValue(key + "/compact", compact)
        self.stack.setCurrentIndex(0 if compact else 1)
        self.menuBar().setVisible(not compact)
        if compact:
            self.resize(self.settings.value(key + "/compact_size", QtCore.QSize(330, 330)))
        else:
            self.resize(self.settings.value(key + "/size", self.DEFAULT_SIZE))
        snap = self.controller.sampler.last
        if snap is not None:
            self.on_snapshot(snap)

    def _summary(self, summary):
        self.menuBar().setVisible(not summary)
        self.tabs.tabBar().setVisible(not summary)
        if summary:
            self._full_size = self.size()
            self.resize(240, max(260, self.perf.side_widget.sizeHint().height() + 10))
        elif getattr(self, "_full_size", None) is not None:
            self.resize(self._full_size)

    # -- data ----------------------------------------------------------------------
    def on_snapshot(self, snap):
        if self.compact:
            self.compact_view.update_snapshot(snap)
            return
        self.perf.update_snapshot(snap)
        current = self.tabs.currentWidget()
        if current in (self.procs, self.users, self.details):
            current.update_snapshot(snap)
        elif current is self.startup and self.WIN10:
            current.update_snapshot(snap)
        elif current is not None and current is self.tux_panel:
            current.update_snapshot(snap)

    def _load_service_pids(self):
        def done(result, error):
            if error is None:
                self.details.service_pids = svc_backend.services_by_pid(result)

        run_async(svc_backend.list_services, done, self)

    def goto_details(self, pid):
        self.tabs.setCurrentWidget(self.details)
        self.details.select_pid(pid)

    def goto_service(self, pid):
        self.tabs.setCurrentWidget(self.services)
        QtCore.QTimer.singleShot(800, lambda: self.services.select_pid(pid))

    def closeEvent(self, event):
        key = self.LAYOUT + ("/compact_size" if self.compact else "/size")
        self.settings.setValue(key, self.size())
        self.controller.window_closed(self)
        super().closeEvent(event)

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.Type.WindowStateChange and self.isMinimized():
            self.controller.window_minimized(self)
        super().changeEvent(event)
