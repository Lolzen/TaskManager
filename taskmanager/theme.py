"""Light and dark colour schemes shared by every layout.

Stylesheets are written as ``string.Template`` text with ``$token``
placeholders and filled with :func:`css`; painted widgets ask :func:`c` or
:func:`qcolor`. The light values are the original Windows colours. Windows 7, 8
and 10 never had a dark Task Manager, so the dark values follow the dark
Task Manager of Windows 11 (neutral greys, a blue accent and a muted amber
heat map).
"""

import os
import shutil
import string
import subprocess

from .qt import QtCore, QtGui

THEMES = ("system", "light", "dark")
THEME_NAMES = {"system": "&System default", "light": "&Light", "dark": "&Dark"}

LIGHT = {
    # general
    "window_bg": "#F0F0F0", "base_bg": "#FFFFFF", "alt_bg": "#F7F7F7", "text": "#000000",
    "subtle_text": "#707070", "disabled_text": "#838383", "border": "#D9D9D9", "separator": "#E5E5E5",
    "hover_bg": "#E5F3FF", "selected_bg": "#CCE8FF", "selected_text": "#000000", "tab_hover": "#E5F1FB",
    "link": "#0066CC", "link_hover": "#3399FF", "tooltip_bg": "#FFFFFF", "tooltip_text": "#575757",
    "highlight": "#3399FF", "highlight_text": "#FFFFFF", "placeholder": "#6D6D6D",
    # Windows 8/10 header, groups and heat map
    "header_text": "#4C607A", "group_text": "#1E3287", "caret": "#97A5B9",
    "heat0": "#FFF4C4", "heat1": "#FFE7A1", "heat2": "#FFC66B", "heat3": "#F99E44",
    "graph_bg": "#FFFFFF", "vline": "#C0C0C0",
    # Windows 8 buttons
    "btn_top": "#F0F0F0", "btn_bottom": "#E5E5E5", "btn_border": "#ACACAC",
    "btn_hover_top": "#ECF4FC", "btn_hover_bottom": "#DCECFC", "btn_hover_border": "#7EB4EA",
    "btn_pressed_top": "#DAECFC", "btn_pressed_bottom": "#C4E0FC", "btn_pressed_border": "#569DE5",
    "btn_disabled_bg": "#F4F4F4", "btn_disabled_border": "#ADB2B5",
    # Windows 10 flat controls and menus
    "w10_btn": "#E1E1E1", "w10_btn_border": "#ADADAD", "w10_btn_hover": "#E5F1FB",
    "w10_btn_hover_border": "#0078D7", "w10_btn_pressed": "#CCE4F7", "w10_btn_pressed_border": "#005499",
    "w10_btn_disabled": "#CCCCCC", "w10_btn_disabled_border": "#BFBFBF",
    "w10_menu_bg": "#F2F2F2", "w10_menu_border": "#CCCCCC", "w10_menu_selected": "#91C9F7",
    # Windows 7 Aero gradients
    "w7_window": "#F0F0F0", "w7_pane": "#FFFFFF", "w7_pane_border": "#898C95", "w7_list_border": "#828790",
    "w7_g1": "#F2F2F2", "w7_g2": "#EBEBEB", "w7_g3": "#DDDDDD", "w7_g4": "#CFCFCF",
    "w7_h1": "#EAF6FD", "w7_h2": "#D9F0FC", "w7_h3": "#BEE6FD", "w7_h4": "#A7D9F5",
    "w7_p1": "#E5F4FC", "w7_p2": "#C4E5F6", "w7_p3": "#98D1EF", "w7_p4": "#68B3DB",
    "w7_btn_border": "#707070", "w7_hover_border": "#3C7FB1", "w7_pressed_border": "#2C628B",
    "w7_header_top": "#FFFFFF", "w7_header_bottom": "#F1F2F4", "w7_header_line": "#D5D5D5",
    "w7_group_border": "#D5DFE5", "w7_status_line": "#D7D7D7", "w7_status_sep": "#C0C0C0",
    "w7_selected": "#3399FF", "w7_selected_text": "#FFFFFF",
}

DARK = {
    "window_bg": "#202020", "base_bg": "#191919", "alt_bg": "#232323", "text": "#FFFFFF",
    "subtle_text": "#A0A0A0", "disabled_text": "#6E6E6E", "border": "#3A3A3A", "separator": "#2E2E2E",
    "hover_bg": "#2A2D33", "selected_bg": "#1F3B57", "selected_text": "#FFFFFF", "tab_hover": "#2A2D33",
    "link": "#4CC2FF", "link_hover": "#99D9FF", "tooltip_bg": "#2B2B2B", "tooltip_text": "#FFFFFF",
    "highlight": "#0078D4", "highlight_text": "#FFFFFF", "placeholder": "#8A8A8A",
    "header_text": "#B4C0D0", "group_text": "#8FB8FF", "caret": "#7C8798",
    "heat0": "#2A2619", "heat1": "#47391A", "heat2": "#73501A", "heat3": "#A2601C",
    "graph_bg": "#1B1B1B", "vline": "#4A4A4A",
    "btn_top": "#383838", "btn_bottom": "#2F2F2F", "btn_border": "#505050",
    "btn_hover_top": "#3F4650", "btn_hover_bottom": "#353C46", "btn_hover_border": "#4CC2FF",
    "btn_pressed_top": "#2B3540", "btn_pressed_bottom": "#26303A", "btn_pressed_border": "#2E9BE0",
    "btn_disabled_bg": "#2A2A2A", "btn_disabled_border": "#3A3A3A",
    "w10_btn": "#333333", "w10_btn_border": "#4D4D4D", "w10_btn_hover": "#3D3D3D",
    "w10_btn_hover_border": "#4CC2FF", "w10_btn_pressed": "#2B2B2B", "w10_btn_pressed_border": "#2E9BE0",
    "w10_btn_disabled": "#2A2A2A", "w10_btn_disabled_border": "#3A3A3A",
    "w10_menu_bg": "#2B2B2B", "w10_menu_border": "#404040", "w10_menu_selected": "#3A4A5C",
    "w7_window": "#2B2B2B", "w7_pane": "#1E1E1E", "w7_pane_border": "#4A4D55", "w7_list_border": "#4A4D55",
    "w7_g1": "#454545", "w7_g2": "#3D3D3D", "w7_g3": "#333333", "w7_g4": "#2B2B2B",
    "w7_h1": "#3B4A57", "w7_h2": "#34434F", "w7_h3": "#2C3B47", "w7_h4": "#26343F",
    "w7_p1": "#2C3A46", "w7_p2": "#26333E", "w7_p3": "#202C36", "w7_p4": "#1A252E",
    "w7_btn_border": "#5A5A5A", "w7_hover_border": "#4C9BD6", "w7_pressed_border": "#3C7FB1",
    "w7_header_top": "#2E2E2E", "w7_header_bottom": "#262626", "w7_header_line": "#3D3D3D",
    "w7_group_border": "#43474D", "w7_status_line": "#3D3D3D", "w7_status_sep": "#4A4A4A",
    "w7_selected": "#2F6FB3", "w7_selected_text": "#FFFFFF",
}

# Performance graph line colours (Windows 8/10); fills and grids are derived in dark mode
GRAPH_LIGHT = {
    "cpu": ("#117DBB", "#F1F6FA", "#D9EAF4"),
    "mem": ("#8B12AE", "#F4F2F4", "#ECDEF0"),
    "disk": ("#4DA60C", "#EFF7E9", "#DCEDD0"),
    "net": ("#A74F01", "#FCF3EB", "#F2DECA"),
    "gpu": ("#117DBB", "#F1F6FA", "#D9EAF4"),
    "sensors": ("#C42B1C", "#FCEDEB", "#F4D6D2"),
}
GRAPH_DARK_LINES = {"cpu": "#4CC2FF", "mem": "#C983E6", "disk": "#7FCC4F", "net": "#E89A54",
                    "gpu": "#4CC2FF", "sensors": "#FF6B5B"}

_current = "light"


def _mix(a, b, t):
    ca, cb = QtGui.QColor(a), QtGui.QColor(b)
    return QtGui.QColor(int(ca.red() + (cb.red() - ca.red()) * t), int(ca.green() + (cb.green() - ca.green()) * t),
                        int(ca.blue() + (cb.blue() - ca.blue()) * t)).name().upper()


def current():
    return _current


def is_dark():
    return _current == "dark"


def set_current(name):
    global _current
    _current = "dark" if name == "dark" else "light"


def tokens():
    return DARK if is_dark() else LIGHT


def c(name):
    return tokens()[name]


def qcolor(name):
    return QtGui.QColor(tokens()[name])


def css(template):
    """Fill a ``$token`` stylesheet template with the current scheme."""
    return string.Template(template).substitute(tokens())


def heat_stops():
    t = tokens()
    return (t["heat0"], t["heat1"], t["heat2"], t["heat3"])


def graph_colors(kind):
    """``(line, fill, grid)`` of a Windows 8/10 performance graph."""
    if not is_dark():
        return GRAPH_LIGHT[kind]
    line, bg = GRAPH_DARK_LINES[kind], DARK["graph_bg"]
    return (line, _mix(bg, line, 0.16), _mix(bg, line, 0.26))


def secondary_colors(kind):
    """Second series (kernel time) of a graph: a lighter line and fill."""
    line, fill, _grid = graph_colors(kind)
    if not is_dark():
        return _mix(line, "#FFFFFF", 0.35), _mix(fill, line, 0.12)
    return _mix(DARK["graph_bg"], line, 0.6), _mix(DARK["graph_bg"], line, 0.3)


# -- choosing the scheme ----------------------------------------------------------------

def system_prefers_dark(app=None):
    """Ask Qt first (6.5+ knows the desktop's colour scheme), then GNOME."""
    hints = QtGui.QGuiApplication.styleHints() if QtGui.QGuiApplication.instance() else None
    scheme = getattr(hints, "colorScheme", None)
    if scheme is not None:
        value = scheme()
        if value == QtCore.Qt.ColorScheme.Dark:
            return True
        if value == QtCore.Qt.ColorScheme.Light:
            return False
    gtk = os.environ.get("GTK_THEME", "")
    if gtk:
        return gtk.lower().endswith(":dark") or gtk.lower().endswith("-dark")
    if shutil.which("gsettings"):
        try:
            out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                                 capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        if "prefer-dark" in out:
            return True
    return False


def resolve(preference):
    """``system``/``light``/``dark`` -> ``light`` or ``dark``."""
    if preference == "dark":
        return "dark"
    if preference == "light":
        return "light"
    return "dark" if system_prefers_dark() else "light"


def apply(app, name):
    """Make ``name`` the current scheme and give the application its palette."""
    set_current(name)
    # setStyle() re-polishes every widget, so only do it once
    if app.style().name().lower() != "fusion":
        app.setStyle("Fusion")
    t = tokens()
    role = QtGui.QPalette.ColorRole
    pal = QtGui.QPalette()
    for r, key in ((role.Window, "window_bg"), (role.WindowText, "text"), (role.Base, "base_bg"),
                   (role.AlternateBase, "alt_bg"), (role.Text, "text"), (role.Button, "window_bg"),
                   (role.ButtonText, "text"), (role.Highlight, "highlight"),
                   (role.HighlightedText, "highlight_text"), (role.ToolTipBase, "tooltip_bg"),
                   (role.ToolTipText, "tooltip_text"), (role.Link, "link"), (role.PlaceholderText, "placeholder"),
                   (role.BrightText, "text")):
        pal.setColor(r, QtGui.QColor(t[key]))
    disabled = QtGui.QPalette.ColorGroup.Disabled
    for r in (role.Text, role.WindowText, role.ButtonText):
        pal.setColor(disabled, r, QtGui.QColor(t["disabled_text"]))
    app.setPalette(pal)
