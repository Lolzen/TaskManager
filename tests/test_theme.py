import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("taskmanager.qt")

from taskmanager import theme  # noqa: E402
from taskmanager.qt import QtCore, QtGui  # noqa: E402


@pytest.fixture(autouse=True)
def restore_light():
    yield
    theme.set_current("light")


def test_both_schemes_define_the_same_tokens():
    assert set(theme.LIGHT) == set(theme.DARK)
    for value in list(theme.LIGHT.values()) + list(theme.DARK.values()):
        assert QtGui.QColor(value).isValid(), value


@pytest.mark.parametrize("name", ["light", "dark"])
def test_every_stylesheet_template_fills(name):
    from taskmanager.win7.window import STYLE as WIN7
    from taskmanager.win8.common import STYLE as WIN8
    from taskmanager.win10.window import STYLE as WIN10
    theme.set_current(name)
    for template in (WIN7, WIN8, WIN10):
        sheet = theme.css(template)  # raises KeyError on an unknown $token
        assert "$" not in sheet


def test_light_scheme_keeps_the_original_windows_colours():
    theme.set_current("light")
    assert theme.graph_colors("cpu") == ("#117DBB", "#F1F6FA", "#D9EAF4")
    assert theme.heat_stops() == ("#FFF4C4", "#FFE7A1", "#FFC66B", "#F99E44")


def test_dark_scheme_is_dark():
    theme.set_current("dark")
    assert QtGui.QColor(theme.c("base_bg")).lightness() < 40
    assert QtGui.QColor(theme.c("text")).lightness() > 200
    line, fill, grid = theme.graph_colors("mem")
    # fills and grids are derived from the line on the dark graph background
    assert QtGui.QColor(fill).lightness() < QtGui.QColor(grid).lightness() < QtGui.QColor(line).lightness()


def test_resolve(monkeypatch):
    assert theme.resolve("dark") == "dark"
    assert theme.resolve("light") == "light"
    monkeypatch.setattr(theme, "system_prefers_dark", lambda app=None: True)
    assert theme.resolve("system") == "dark"
    monkeypatch.setattr(theme, "system_prefers_dark", lambda app=None: False)
    assert theme.resolve("system") == "light"


def test_gtk_theme_variable(monkeypatch):
    monkeypatch.setenv("GTK_THEME", "Adwaita:dark")
    hints = QtGui.QGuiApplication.styleHints() if QtGui.QGuiApplication.instance() else None
    if hints is not None and hasattr(hints, "colorScheme") and \
            hints.colorScheme() != QtCore.Qt.ColorScheme.Unknown:
        pytest.skip("the platform reports a colour scheme itself")
    assert theme.system_prefers_dark() is True
