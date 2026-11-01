"""Windows 10 Task Manager layout.

It is the Windows 8 layout plus what Windows 10 added: GPU columns and
pages, Power usage columns, disk types, RAM and Wi-Fi details, Architecture and
Elevated columns, Last BIOS time and Running now on the Startup tab, history for
all processes, a default tab and full account names.
"""

from ..qt import QtCore, QtGui
from ..win8.common import STYLE as WIN8_STYLE
from ..win8.window import Win8Window

# Windows 10 kept the Windows 8 design but switched to its flatter controls.
STYLE = WIN8_STYLE + """
QPushButton { background: $w10_btn; border: 1px solid $w10_btn_border; padding: 3px 16px; }
QPushButton:hover { background: $w10_btn_hover; border-color: $w10_btn_hover_border; }
QPushButton:pressed { background: $w10_btn_pressed; border-color: $w10_btn_pressed_border; }
QPushButton:disabled { background: $w10_btn_disabled; border-color: $w10_btn_disabled_border; color: $disabled_text; }
QTabBar::tab:hover:!selected { background: $hover_bg; border-color: $hover_bg; }
QMenu { background: $w10_menu_bg; border: 1px solid $w10_menu_border; color: $text; }
QMenu::item { padding: 4px 28px 4px 24px; }
QMenu::item:selected { background: $w10_menu_selected; color: $text; }
"""


class Win10Window(Win8Window):
    LAYOUT = "win10"
    WIN10 = True
    STYLE = STYLE
    DEFAULT_SIZE = QtCore.QSize(760, 660)

    def initial_tab(self):
        """Windows 10 opens the tab picked in Options > Set default tab."""
        return self.settings.value("win10/default_tab", 0, type=int)

    def extend_menus(self, options, view):
        options.addSeparator()
        default = options.addMenu("Set &default tab")
        group = QtGui.QActionGroup(default)
        current = self.initial_tab()
        for index in range(self.tabs.count()):
            act = default.addAction(self.tabs.tabText(index),
                                    lambda i=index: self.settings.setValue("win10/default_tab", i))
            act.setCheckable(True)
            act.setChecked(index == current)
            group.addAction(act)

        full = options.addAction("Show &full account name", self._full_names)
        full.setCheckable(True)
        full.setChecked(self.settings.value("win10/full_names", False, type=bool))
        self._full_names(full.isChecked())

        history = options.addAction("Show history for all &processes", self._all_history)
        history.setCheckable(True)
        history.setChecked(self.settings.value("win10/history_all", False, type=bool))
        self._all_history(history.isChecked())

    def _full_names(self, checked):
        self.settings.setValue("win10/full_names", checked)
        self.users.full_names = checked
        if self.controller.sampler.last is not None and self.tabs.currentWidget() is self.users:
            self.users.update_snapshot(self.controller.sampler.last)

    def _all_history(self, checked):
        self.settings.setValue("win10/history_all", checked)
        self.history.all_processes = checked
        if self.history.isVisible():
            self.history.refresh()
