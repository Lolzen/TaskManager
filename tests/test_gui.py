"""Smoke tests: both layouts build and render a live snapshot off-screen."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

qt = pytest.importorskip("taskmanager.qt")
from taskmanager.qt import QtCore, QtWidgets  # noqa: E402


@pytest.fixture(scope="module")
def qapp(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    os.environ["XDG_DATA_HOME"] = str(home / "data")
    os.environ["XDG_CONFIG_HOME"] = str(home / "config")
    QtCore.QCoreApplication.setOrganizationName("TaskManagerTests")
    QtCore.QCoreApplication.setApplicationName("TaskManagerTests")
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
    QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope,
                             str(home / "settings"))
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["test"])
    from taskmanager.app import apply_light_palette
    apply_light_palette(app)
    return app


def _wait_for_snapshot(app, controller, count=2, timeout=10000):
    seen = []
    controller.sampler.snapshot.connect(seen.append)
    timer = QtCore.QElapsedTimer()
    timer.start()
    while len(seen) < count and timer.elapsed() < timeout:
        app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 50)
    return seen


@pytest.mark.parametrize("layout", ["win7", "win8", "win10"])
def test_layout_renders_every_tab(qapp, layout):
    from taskmanager.app import Controller
    controller = Controller(qapp, layout)
    controller.set_speed("High")
    try:
        assert _wait_for_snapshot(qapp, controller), "sampler produced no data"
        window = controller.window
        assert window.LAYOUT == layout
        for index in range(window.tabs.count()):
            window.tabs.setCurrentIndex(index)
            qapp.processEvents()
            assert not window.grab().isNull()
        snap = controller.sampler.last
        window.on_snapshot(snap)
        from taskmanager.widgets.dialogs import process_menu
        me = snap.procs[os.getpid()]
        texts = [a.text() for a in process_menu(window, me, win8=layout != "win7").actions()]
        assert ("End task" if layout != "win7" else "End Process") in texts
        if layout in ("win8", "win10"):
            window.set_compact(True)
            window.on_snapshot(snap)
            window.set_compact(False)
            assert "%" in window.perf.items["cpu"].sub.text()
        else:
            assert window.status_procs.text().startswith("Processes: ")
    finally:
        controller.window._switching = True
        controller.window.close()
        controller._shutdown()


def test_switch_layout(qapp):
    from taskmanager.app import Controller
    controller = Controller(qapp, "win7")
    try:
        controller.switch_layout("win8")
        assert controller.window.LAYOUT == "win8"
        assert QtCore.QSettings().value("layout") == "win8"
    finally:
        controller.window._switching = True
        controller.window.close()
        controller._shutdown()


@pytest.mark.parametrize("layout", ["win7", "win8", "win10"])
def test_tux_mode_adds_tab_and_columns(qapp, layout):
    from taskmanager.app import Controller
    controller = Controller(qapp, layout, tux=True)
    controller.set_speed("High")
    try:
        _wait_for_snapshot(qapp, controller, count=3)
        window = controller.window
        assert "Tux mode" in window.windowTitle()
        titles = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        assert titles[-1] == "Tux"
        window.tabs.setCurrentIndex(len(titles) - 1)
        window.on_snapshot(controller.sampler.last)
        sections = [window.tux_panel.tree.topLevelItem(i).text(0)
                    for i in range(window.tux_panel.tree.topLevelItemCount())]
        assert "Load" in sections and "Kernel limits" in sections
        procs = window.procs if layout == "win7" else window.details
        header = procs.tree.headerItem()
        labels = [header.text(i) for i in range(header.columnCount())]
        assert "systemd unit" in labels and "OOM score" in labels
        for index in range(window.tabs.count()):
            window.tabs.setCurrentIndex(index)
            qapp.processEvents()
        # switching Tux mode off rebuilds the same layout without it
        controller.set_tux(False)
        assert controller.window.LAYOUT == layout
        assert "Tux mode" not in controller.window.windowTitle()
    finally:
        controller.window._switching = True
        controller.window.close()
        controller._shutdown()
