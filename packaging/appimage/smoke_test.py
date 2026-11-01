"""Run the bundled Task Manager headlessly: every layout, Tux mode, both themes.

Used by test-appimage.sh with the AppImage's own interpreter, so it proves
the bundled Python, PySide6 and Qt plugins work on the host distribution.
"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
home = tempfile.mkdtemp(prefix="taskmanager-smoke-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(home, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(home, "data")

from taskmanager import __file__ as package_file, __version__, theme  # noqa: E402
from taskmanager.app import Controller, apply_fonts  # noqa: E402
from taskmanager.qt import BINDING, QtCore, QtWidgets  # noqa: E402


def wait_for_snapshots(app, controller, count=2, timeout_ms=15000):
    seen = []
    controller.sampler.snapshot.connect(seen.append)
    timer = QtCore.QElapsedTimer()
    timer.start()
    while len(seen) < count and timer.elapsed() < timeout_ms:
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
    return seen


def main():
    QtCore.QCoreApplication.setOrganizationName("TaskManagerSmokeTest")
    QtCore.QCoreApplication.setApplicationName("TaskManagerSmokeTest")
    app = QtWidgets.QApplication(["smoke-test"])
    apply_fonts(app)
    print("taskmanager {} from {} ({}, Python {})".format(
        __version__, os.path.dirname(package_file), BINDING, sys.version.split()[0]))
    failures = 0
    for scheme in ("light", "dark"):
        for layout in ("win7", "win8", "win10"):
            controller = Controller(app, layout, tux=True, theme_pref=scheme)
            controller.set_speed("High")
            try:
                if not wait_for_snapshots(app, controller):
                    raise RuntimeError("no data from the sampler")
                window = controller.window
                for index in range(window.tabs.count()):
                    window.tabs.setCurrentIndex(index)
                    window.on_snapshot(controller.sampler.last)
                    app.processEvents()
                    if window.grab().isNull():
                        raise RuntimeError("tab {} did not render".format(window.tabs.tabText(index)))
                assert theme.current() == scheme
                print("ok   {:5} {:5} {} tabs".format(scheme, layout, window.tabs.count()))
            except Exception as exc:  # noqa: BLE001 - report every combination
                failures += 1
                print("FAIL {:5} {:5} {}".format(scheme, layout, exc))
            finally:
                controller.window._switching = True
                controller.window.close()
                controller._shutdown()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
