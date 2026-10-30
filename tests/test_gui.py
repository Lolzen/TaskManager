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


def test_dialogs_and_menus_build(qapp):
    """Exercise the code paths the layout tests do not reach (both Qt bindings)."""
    from taskmanager.app import Controller
    from taskmanager.widgets import dialogs
    from taskmanager.widgets.tree import ColumnChooser
    controller = Controller(qapp, "win10", tux=True)
    controller.set_speed("High")
    try:
        _wait_for_snapshot(qapp, controller, count=2)
        window = controller.window
        snap = controller.sampler.last
        me = snap.procs[os.getpid()]
        for widget in (dialogs.RunDialog(window, win8=True), dialogs.RunDialog(window),
                       dialogs.AffinityDialog("x", [0], 2, window), dialogs.PropertiesDialog(me, window),
                       dialogs.AboutDialog(window, "Task Manager"),
                       ColumnChooser("t", "x", ["A", "B"], ["A"], window)):
            widget.show()
            qapp.processEvents()
            widget.close()
        for win8 in (False, True):
            menu = dialogs.process_menu(window, me, win8=win8)
            assert menu.actions()
        # every menu bar entry can be built and its submenus listed
        for action in window.menuBar().actions():
            assert action.menu() is not None and action.menu().actions()
        window.procs.update_snapshot(snap)
        window.procs.set_group_by_type(False)
        window.procs.set_group_by_type(True)
        window.perf.set_graphs_hidden(True)
        window.perf.toggle_summary()
        window.perf.toggle_summary()
        window.perf.page_for["cpu"].set_logical(True)
        window.perf.page_for["cpu"].copy()
        window.set_compact(True)
        window.set_compact(False)
        controller.switch_layout("win7")
        controller.window.procs.choose_columns  # attribute exists
        controller.window.perf.set_cpu_mode(False)
        controller.window.on_snapshot(snap)
    finally:
        controller.window._switching = True
        controller.window.close()
        controller._shutdown()
