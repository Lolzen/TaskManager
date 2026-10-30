"""Application entry point and the controller shared by both layouts."""

import argparse
import signal
import sys

from . import __version__
from .backend.history import AppHistory
from .core import SamplerThread
from .qt import QtCore, QtGui, QtWidgets, Qt

HELP_URL = "https://github.com/Lolzen/TaskManager#readme"
LAYOUTS = ("win7", "win8")


def apply_light_palette(app):
    """Both Task Managers are light themed regardless of the desktop theme."""
    app.setStyle("Fusion")
    pal = QtGui.QPalette()
    roles = {
        QtGui.QPalette.ColorRole.Window: "#F0F0F0",
        QtGui.QPalette.ColorRole.WindowText: "#000000",
        QtGui.QPalette.ColorRole.Base: "#FFFFFF",
        QtGui.QPalette.ColorRole.AlternateBase: "#F7F7F7",
        QtGui.QPalette.ColorRole.Text: "#000000",
        QtGui.QPalette.ColorRole.Button: "#F0F0F0",
        QtGui.QPalette.ColorRole.ButtonText: "#000000",
        QtGui.QPalette.ColorRole.Highlight: "#3399FF",
        QtGui.QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QtGui.QPalette.ColorRole.ToolTipBase: "#FFFFFF",
        QtGui.QPalette.ColorRole.ToolTipText: "#575757",
        QtGui.QPalette.ColorRole.Link: "#0066CC",
        QtGui.QPalette.ColorRole.PlaceholderText: "#6D6D6D",
    }
    for role, color in roles.items():
        pal.setColor(role, QtGui.QColor(color))
    pal.setColor(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.Text, QtGui.QColor("#6D6D6D"))
    pal.setColor(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("#6D6D6D"))
    pal.setColor(QtGui.QPalette.ColorGroup.Disabled, QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor("#838383"))
    app.setPalette(pal)
    font = QtGui.QFont()
    font.setFamilies(["Segoe UI", "Selawik", "Noto Sans", "Open Sans", "DejaVu Sans", "Liberation Sans"])
    font.setPointSizeF(9)
    app.setFont(font)


def tray_pixmap(cpu):
    """The little CPU meter Task Manager shows in the notification area."""
    pix = QtGui.QPixmap(16, 16)
    pix.fill(Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pix)
    p.fillRect(2, 0, 12, 16, QtGui.QColor("#000000"))
    height = int(round(14 * min(100.0, cpu) / 100.0))
    p.fillRect(4, 15 - height, 8, height, QtGui.QColor("#00FF00"))
    p.setPen(QtGui.QColor("#008040"))
    for y in range(1, 15, 2):
        p.drawLine(4, y, 11, y)
    p.end()
    return pix


class Controller(QtCore.QObject):
    def __init__(self, app, layout):
        super().__init__()
        self.app = app
        self.settings = QtCore.QSettings()
        self.sampler = SamplerThread(self)
        self.history = AppHistory()
        self.window = None
        self.always_on_top = self.settings.value("options/on_top", True, type=bool)
        self.minimize_on_use = self.settings.value("options/min_on_use", True, type=bool)
        self.hide_when_minimized = self.settings.value("options/hide_min", False, type=bool)
        self.sampler.set_speed(self.settings.value("options/speed", "Normal"))
        self.sampler.snapshot.connect(self._on_snapshot)

        self.tray = None
        if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QtWidgets.QSystemTrayIcon(QtGui.QIcon(tray_pixmap(0)), self)
            self.tray.activated.connect(self._tray_activated)
            menu = QtWidgets.QMenu()
            menu.addAction("Restore", self.restore)
            menu.addAction("Exit Task Manager", self.quit)
            self.tray.setContextMenu(menu)
            self._tray_menu = menu
            self.tray.show()

        self.history_timer = QtCore.QTimer(self)
        self.history_timer.timeout.connect(self.history.save)
        self.history_timer.start(60000)
        app.aboutToQuit.connect(self._shutdown)
        self.switch_layout(layout)

    # -- layouts -------------------------------------------------------------
    def switch_layout(self, layout):
        old = self.window
        if layout == "win8":
            from .win8.window import Win8Window as cls
        else:
            from .win7.window import Win7Window as cls
        self.window = cls(self)
        self.window.setWindowIcon(QtGui.QIcon(tray_pixmap(60)))
        self._apply_on_top()
        if old is not None:
            self.window.move(old.pos())
            old._switching = True
            old.close()
            old.deleteLater()
        self.settings.setValue("layout", layout)
        self.window.show()

    def window_closed(self, window):
        if getattr(window, "_switching", False):
            return
        self.app.quit()

    def window_minimized(self, window):
        if self.hide_when_minimized and self.tray is not None:
            QtCore.QTimer.singleShot(0, window.hide)

    def restore(self):
        if self.window is None:
            return
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _tray_activated(self, reason):
        if reason in (QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick,
                      QtWidgets.QSystemTrayIcon.ActivationReason.Trigger):
            self.restore()

    # -- options -------------------------------------------------------------
    def _apply_on_top(self):
        if self.window is None:
            return
        visible = self.window.isVisible()
        self.window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.always_on_top)
        if visible:
            self.window.show()

    def set_always_on_top(self, checked):
        self.always_on_top = checked
        self.settings.setValue("options/on_top", checked)
        self._apply_on_top()

    def set_minimize_on_use(self, checked):
        self.minimize_on_use = checked
        self.settings.setValue("options/min_on_use", checked)

    def set_hide_when_minimized(self, checked):
        self.hide_when_minimized = checked
        self.settings.setValue("options/hide_min", checked)

    def set_speed(self, name):
        self.sampler.set_speed(name)
        self.settings.setValue("options/speed", name)

    def used_window(self):
        """Called after *Switch to* / *Run new task* (Options > Minimize on use)."""
        if self.minimize_on_use and self.window is not None:
            self.window.showMinimized()

    def open_help(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(HELP_URL))

    # -- data ----------------------------------------------------------------
    def _on_snapshot(self, snap):
        self.history.update(snap)
        if self.tray is not None:
            self.tray.setIcon(QtGui.QIcon(tray_pixmap(snap.cpu.total)))
            self.tray.setToolTip("CPU Usage: {:.0f}%\nPhysical Memory: {:.0f}%".format(
                snap.cpu.total, snap.mem.percent))
        if self.window is not None:
            self.window.on_snapshot(snap)

    def quit(self):
        self.app.quit()

    def _shutdown(self):
        self.history.save()
        self.sampler.stop()
        if self.tray is not None:
            self.tray.hide()


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="taskmanager", description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--layout", choices=LAYOUTS, help="which Task Manager to show")
    group.add_argument("--win7", dest="layout", action="store_const", const="win7",
                       help="shortcut for --layout win7")
    group.add_argument("--win8", dest="layout", action="store_const", const="win8",
                       help="shortcut for --layout win8")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    return parser.parse_known_args(argv)


def main(argv=None):
    args, qt_args = parse_args(sys.argv[1:] if argv is None else argv)
    QtCore.QCoreApplication.setOrganizationName("TaskManager")
    QtCore.QCoreApplication.setApplicationName("TaskManager")
    app = QtWidgets.QApplication([sys.argv[0]] + qt_args)
    app.setQuitOnLastWindowClosed(False)
    app.setDesktopFileName("taskmanager")
    apply_light_palette(app)
    layout = args.layout or QtCore.QSettings().value("layout", "win8")
    if layout not in LAYOUTS:
        layout = "win8"
    controller = Controller(app, layout)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # wake the interpreter regularly so Ctrl+C is handled
    keepalive = QtCore.QTimer()
    keepalive.timeout.connect(lambda: None)
    keepalive.start(250)
    code = app.exec()
    del controller
    return code


if __name__ == "__main__":
    sys.exit(main())
