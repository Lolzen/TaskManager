"""Windows 7 Task Manager layout."""

from ..qt import QtCore, QtGui, QtWidgets
from ..widgets.dialogs import AboutDialog, RunDialog
from ..widgets.services import ServicesPanel
from .lists import ApplicationsTab, ProcessesTab, UsersTab
from .performance import NetworkingTab, PerformanceTab

STYLE = """
QMainWindow, QDialog { background: #F0F0F0; }
QTabWidget::pane { border: 1px solid #898C95; background: #FFFFFF; top: -1px; }
QTabBar::tab {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #F2F2F2, stop:0.5 #EBEBEB, stop:0.51 #DDDDDD, stop:1 #CFCFCF);
    border: 1px solid #898C95; border-bottom: none; padding: 3px 8px; margin-right: -1px; margin-top: 2px;
}
QTabBar::tab:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #EAF6FD, stop:0.5 #D9F0FC, stop:0.51 #BEE6FD, stop:1 #A7D9F5); }
QTabBar::tab:selected { background: #FFFFFF; margin-top: 0px; padding-bottom: 5px; }
QTreeWidget { border: 1px solid #828790; background: #FFFFFF; }
QTreeWidget::item { padding: 0px 2px; }
QTreeWidget::item:selected { background: #3399FF; color: #FFFFFF; }
QHeaderView::section {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFFFFF, stop:1 #F1F2F4);
    border: none; border-right: 1px solid #D5D5D5; border-bottom: 1px solid #D5D5D5; padding: 2px 4px;
}
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #F2F2F2, stop:0.5 #EBEBEB, stop:0.51 #DDDDDD, stop:1 #CFCFCF);
    border: 1px solid #707070; border-radius: 3px; padding: 3px 12px; min-height: 16px;
}
QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #EAF6FD, stop:0.5 #D9F0FC, stop:0.51 #BEE6FD, stop:1 #A7D9F5); border-color: #3C7FB1; }
QPushButton:pressed { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #E5F4FC, stop:0.5 #C4E5F6, stop:0.51 #98D1EF, stop:1 #68B3DB); border-color: #2C628B; }
QPushButton:disabled { background: #F4F4F4; border-color: #ADB2B5; color: #838383; }
QGroupBox { border: 1px solid #D5DFE5; border-radius: 3px; margin-top: 8px; padding-top: 4px; }
QGroupBox::title { subcontrol-origin: margin; left: 7px; padding: 0 2px; }
QStatusBar { background: #F0F0F0; border-top: 1px solid #D7D7D7; }
QStatusBar::item { border: none; border-right: 1px solid #C0C0C0; }
QMenuBar { background: #F0F0F0; }
"""


class Win7Window(QtWidgets.QMainWindow):
    LAYOUT = "win7"

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setObjectName("win7")
        self.setWindowTitle("Windows Task Manager")
        self.setStyleSheet(STYLE)
        self.settings = QtCore.QSettings()

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(False)
        self.apps = ApplicationsTab()
        self.procs = ProcessesTab()
        self.services = ServicesPanel(win8=False)
        self.perf = PerformanceTab()
        self.net = NetworkingTab()
        self.users = UsersTab()
        for widget, title in ((self.apps, "Applications"), (self.procs, "Processes"),
                              (self.services, "Services"), (self.perf, "Performance"),
                              (self.net, "Networking"), (self.users, "Users")):
            self.tabs.addTab(widget, title)
        central = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(central)
        lay.setContentsMargins(6, 6, 6, 4)
        lay.addWidget(self.tabs)
        self.setCentralWidget(central)

        self.apps.goto_pid.connect(self.goto_process)
        self.apps.used.connect(controller.used_window)
        self.services.goto_pid.connect(self.goto_process)

        self.status_procs = QtWidgets.QLabel()
        self.status_cpu = QtWidgets.QLabel()
        self.status_mem = QtWidgets.QLabel()
        bar = self.statusBar()
        bar.setSizeGripEnabled(True)
        for label, stretch in ((self.status_procs, 1), (self.status_cpu, 1), (self.status_mem, 2)):
            label.setContentsMargins(4, 0, 4, 0)
            bar.addWidget(label, stretch)

        self._build_menus()
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.setCurrentIndex(self.settings.value("win7/tab", 1, type=int))
        self._tab_changed(self.tabs.currentIndex())
        self.resize(self.settings.value("win7/size", QtCore.QSize(460, 540)))

        if controller.sampler.last is not None:
            self.on_snapshot(controller.sampler.last)

    # -- menus --------------------------------------------------------------
    def _build_menus(self):
        mb = self.menuBar()
        c = self.controller

        file_menu = mb.addMenu("&File")
        file_menu.addAction("&New Task (Run...)", lambda: RunDialog(self).exec())
        file_menu.addSeparator()
        file_menu.addAction("E&xit Task Manager", c.quit)

        opts = mb.addMenu("&Options")
        self.act_top = opts.addAction("&Always On Top", c.set_always_on_top)
        self.act_top.setCheckable(True)
        self.act_top.setChecked(c.always_on_top)
        self.act_min = opts.addAction("&Minimize On Use", c.set_minimize_on_use)
        self.act_min.setCheckable(True)
        self.act_min.setChecked(c.minimize_on_use)
        self.act_hide = opts.addAction("&Hide When Minimized", c.set_hide_when_minimized)
        self.act_hide.setCheckable(True)
        self.act_hide.setChecked(c.hide_when_minimized)
        self.act_full = opts.addAction("Show &Full Account Name", self._full_account)
        self.act_full.setCheckable(True)

        view = mb.addMenu("&View")
        view.addAction("&Refresh Now", c.sampler.refresh_now, QtGui.QKeySequence("F5"))
        speed = view.addMenu("&Update Speed")
        group = QtGui.QActionGroup(speed)
        for name in ("High", "Normal", "Low", "Paused"):
            act = speed.addAction("&" + name, lambda n=name: c.set_speed(n))
            act.setCheckable(True)
            act.setChecked(c.sampler.speed == name)
            group.addAction(act)
        view.addSeparator()
        self.act_columns = view.addAction("&Select Columns...", self.procs.choose_columns)
        self.cpu_history = view.addMenu("&CPU History")
        hist_group = QtGui.QActionGroup(self.cpu_history)
        per_cpu = self.settings.value("win7/per_cpu", True, type=bool)
        for text, value in (("&One Graph, All CPUs", False), ("One Graph &Per CPU", True)):
            act = self.cpu_history.addAction(text, lambda v=value: self._set_cpu_mode(v))
            act.setCheckable(True)
            act.setChecked(per_cpu == value)
            hist_group.addAction(act)
        self.perf.set_cpu_mode(per_cpu)
        self.act_kernel = view.addAction("Show &Kernel Times", self._set_kernel)
        self.act_kernel.setCheckable(True)
        self.act_kernel.setChecked(self.settings.value("win7/kernel", False, type=bool))
        self.perf.set_show_kernel(self.act_kernel.isChecked())
        self.act_netcols = view.addAction("Show &Bytes Sent/Received History", self._set_net_lines)
        self.act_netcols.setCheckable(True)
        view.addSeparator()
        c.add_layout_menu(view, "win7")

        help_menu = mb.addMenu("&Help")
        help_menu.addAction("Task Manager &Help Topics", c.open_help)
        help_menu.addSeparator()
        help_menu.addAction("&About Task Manager", lambda: AboutDialog(self, "Task Manager").exec())

    def _tab_changed(self, index):
        widget = self.tabs.widget(index)
        self.act_columns.setEnabled(widget is self.procs)
        self.cpu_history.setEnabled(widget is self.perf)
        self.act_kernel.setEnabled(widget is self.perf)
        self.act_netcols.setEnabled(widget is self.net)
        self.settings.setValue("win7/tab", index)
        snap = self.controller.sampler.last
        if snap is not None and widget in (self.apps, self.procs, self.users):
            widget.update_snapshot(snap)

    def _full_account(self, checked):
        self.procs.full_account = checked
        if self.procs.snap:
            self.procs.update_snapshot(self.procs.snap)

    def _set_cpu_mode(self, per_cpu):
        self.settings.setValue("win7/per_cpu", per_cpu)
        self.perf.set_cpu_mode(per_cpu)

    def _set_kernel(self, checked):
        self.settings.setValue("win7/kernel", checked)
        self.perf.set_show_kernel(checked)

    def _set_net_lines(self, checked):
        self.net.show_sent_recv = checked

    # -- data -------------------------------------------------------------------
    def on_snapshot(self, snap):
        self.status_procs.setText("Processes: {}".format(snap.process_count))
        self.status_cpu.setText("CPU Usage: {:.0f}%".format(snap.cpu.total))
        self.status_mem.setText("Physical Memory: {:.0f}%".format(snap.mem.percent))
        # Graphs always advance; lists only refresh while visible.
        self.perf.update_snapshot(snap)
        self.net.update_snapshot(snap)
        current = self.tabs.currentWidget()
        if current is self.apps:
            self.apps.update_snapshot(snap)
        elif current is self.procs:
            self.procs.update_snapshot(snap)
        elif current is self.users:
            self.users.update_snapshot(snap)

    def goto_process(self, pid):
        self.tabs.setCurrentWidget(self.procs)
        if self.controller.sampler.last is not None:
            self.procs.update_snapshot(self.controller.sampler.last)
        self.procs.select_pid(pid)

    def closeEvent(self, event):
        self.settings.setValue("win7/size", self.size())
        self.controller.window_closed(self)
        super().closeEvent(event)

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.Type.WindowStateChange and self.isMinimized():
            self.controller.window_minimized(self)
        super().changeEvent(event)
