"""Dialogs and the process context menu shared by both layouts."""

import datetime
import os

import psutil

from ..backend import actions
from ..backend.formatting import fmt_bytes
from ..qt import QtCore, QtGui, QtWidgets, Qt


def show_error(parent, title, exc):
    if isinstance(exc, psutil.AccessDenied) or isinstance(exc, PermissionError):
        detail = "Access is denied."
    elif isinstance(exc, psutil.NoSuchProcess):
        detail = "The process has already exited."
    else:
        detail = str(exc) or exc.__class__.__name__
    QtWidgets.QMessageBox.warning(parent, title, "The operation could not be completed.\n\n" + detail)


def guarded(parent, title, fn, *args):
    try:
        fn(*args)
        return True
    except Exception as exc:  # noqa: BLE001 - shown to the user
        show_error(parent, title, exc)
        return False


def confirm(parent, title, text, info, accept_text):
    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
    box.setText(text)
    box.setInformativeText(info)
    ok = box.addButton(accept_text, QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(ok)
    box.exec()
    return box.clickedButton() is ok


def confirm_end(parent, name, tree=False, win8=False):
    title = "Task Manager" if win8 else "Windows Task Manager"
    if tree:
        text = 'Do you want to end the process tree of "{}"?'.format(name) if win8 else \
            "Do you want to end the process tree of '{}'?".format(name)
        info = ("If open programs or processes are associated with this process tree, they will close "
                "and you will lose any unsaved data. If you end a system process, it might result in "
                "system instability. Are you sure you want to continue?")
        return confirm(parent, title, text, info, "End process tree")
    text = 'Do you want to end "{}"?'.format(name) if win8 else "Do you want to end '{}'?".format(name)
    info = ("If an open program is associated with this process, it will close and you will lose any "
            "unsaved data. If you end a system process, it might result in system instability. "
            "Are you sure you want to continue?")
    return confirm(parent, title, text, info, "End process")


class RunDialog(QtWidgets.QDialog):
    """File > Run new task / New Task..."""

    def __init__(self, parent=None, win8=False):
        super().__init__(parent)
        self.setWindowTitle("Create new task" if win8 else "Create New Task")
        layout = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel()
        icon.setPixmap(self.style().standardIcon(
            QtWidgets.QStyle.StandardPixmap.SP_ComputerIcon).pixmap(32, 32))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        top.addWidget(icon)
        msg = QtWidgets.QLabel("Type the name of a program, folder, document, or Internet resource, "
                               "and it will be opened for you.")
        msg.setWordWrap(True)
        top.addWidget(msg, 1)
        layout.addLayout(top)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("&Open:"))
        self.command = QtWidgets.QComboBox()
        self.command.setEditable(True)
        self.command.setMinimumWidth(280)
        settings = QtCore.QSettings()
        for entry in settings.value("run/history", [], type=list) or []:
            self.command.addItem(entry)
        self.command.setCurrentText("")
        row.addWidget(self.command, 1)
        layout.addLayout(row)
        self.elevated = QtWidgets.QCheckBox("Create this task with administrative privileges.")
        layout.addWidget(self.elevated)
        buttons = QtWidgets.QDialogButtonBox()
        buttons.addButton(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        buttons.addButton(QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        browse = buttons.addButton("&Browse...", QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        browse.clicked.connect(self._browse)
        buttons.accepted.connect(self._run)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Browse", os.path.expanduser("~"))
        if path:
            self.command.setCurrentText(path)

    def _run(self):
        cmd = self.command.currentText().strip()
        if not cmd:
            return
        try:
            actions.run_new_task(cmd, self.elevated.isChecked())
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.critical(
                self, cmd, "Cannot find '{}'. Make sure you typed the name correctly, and then try again.\n\n{}"
                .format(cmd, exc))
            return
        settings = QtCore.QSettings()
        history = [cmd] + [h for h in settings.value("run/history", [], type=list) or [] if h != cmd]
        settings.setValue("run/history", history[:20])
        self.accept()


class AffinityDialog(QtWidgets.QDialog):
    def __init__(self, name, current, ncpu, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Processor Affinity")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("Which processors are allowed to run “{}”?".format(name)))
        self.list = QtWidgets.QListWidget()
        self.all = QtWidgets.QListWidgetItem("<All Processors>")
        self.all.setFlags(self.all.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        self.list.addItem(self.all)
        self.cpus = []
        for i in range(ncpu):
            item = QtWidgets.QListWidgetItem("CPU {}".format(i))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if i in current else Qt.CheckState.Unchecked)
            self.list.addItem(item)
            self.cpus.append(item)
        self.all.setCheckState(Qt.CheckState.Checked if len(current) == ncpu else Qt.CheckState.Unchecked)
        self.list.itemChanged.connect(self._changed)
        layout.addWidget(self.list)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _changed(self, item):
        if item is self.all:
            state = item.checkState()
            self.list.blockSignals(True)
            for cpu in self.cpus:
                cpu.setCheckState(state)
            self.list.blockSignals(False)
        else:
            self.list.blockSignals(True)
            every = all(c.checkState() == Qt.CheckState.Checked for c in self.cpus)
            self.all.setCheckState(Qt.CheckState.Checked if every else Qt.CheckState.Unchecked)
            self.list.blockSignals(False)

    def selected(self):
        return [i for i, item in enumerate(self.cpus) if item.checkState() == Qt.CheckState.Checked]

    def accept(self):
        if not self.selected():
            QtWidgets.QMessageBox.warning(self, "Processor Affinity",
                                          "The process must have affinity with at least one processor.")
            return
        super().accept()


class PropertiesDialog(QtWidgets.QDialog):
    """Process > Properties (a compact version of the Explorer file dialog)."""

    def __init__(self, proc, parent=None):
        super().__init__(parent)
        self.setWindowTitle("{} Properties".format(proc.name))
        layout = QtWidgets.QVBoxLayout(self)
        tabs = QtWidgets.QTabWidget()
        general = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(general)
        size = ""
        if proc.exe:
            try:
                size = "{} ({:,} bytes)".format(fmt_bytes(os.path.getsize(proc.exe)), os.path.getsize(proc.exe))
            except OSError:
                size = ""
        rows = [
            ("Name:", proc.name),
            ("Description:", proc.description),
            ("Location:", os.path.dirname(proc.exe) if proc.exe else "Access denied"),
            ("Size:", size or "Unknown"),
            ("Process ID:", str(proc.pid)),
            ("Parent process ID:", str(proc.ppid)),
            ("User name:", proc.username),
            ("Started:", datetime.datetime.fromtimestamp(proc.create_time).strftime("%A, %B %d, %Y, %H:%M:%S")
             if proc.create_time else ""),
            ("Threads:", str(proc.threads)),
            ("Command line:", proc.cmdline),
        ]
        for label, value in rows:
            field = QtWidgets.QLineEdit(value)
            field.setReadOnly(True)
            field.setFrame(False)
            field.setCursorPosition(0)
            form.addRow(label, field)
        tabs.addTab(general, "General")
        layout.addWidget(tabs)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        self.resize(460, 380)


def process_menu(parent, proc, win8=False, on_changed=None, extra=None):
    """Build the right-click menu of a process row.

    ``extra`` is a list of ``(text, callback)`` added at the top (e.g.
    *Switch to*, *Expand*, *Go to details*); ``None`` entries add separators.
    """
    menu = QtWidgets.QMenu(parent)
    refresh = on_changed or (lambda: None)

    for entry in extra or []:
        if entry is None:
            menu.addSeparator()
        else:
            menu.addAction(entry[0], entry[1])
    if extra:
        menu.addSeparator()

    if not win8:
        menu.addAction("Open File Location", lambda: guarded(parent, "Open File Location",
                                                              actions.open_file_location, proc.exe))
        menu.addSeparator()

    def end():
        if confirm_end(parent, proc.name, win8=win8):
            title = "Unable to Terminate Process"
            if guarded(parent, title, actions.end_process, proc.pid):
                refresh()

    def end_tree():
        if confirm_end(parent, proc.name, tree=True, win8=win8):
            if guarded(parent, "Unable to Terminate Process", actions.end_process_tree, proc.pid):
                refresh()

    menu.addAction("End task" if win8 else "End Process", end)
    menu.addAction("End process tree" if win8 else "End Process Tree", end_tree)
    menu.addSeparator()

    if proc.status == "Suspended":
        menu.addAction("Resume process" if win8 else "Resume Process",
                       lambda: guarded(parent, "Resume", actions.resume, proc.pid) and refresh())
    else:
        menu.addAction("Suspend process" if win8 else "Suspend Process",
                       lambda: guarded(parent, "Suspend", actions.suspend, proc.pid) and refresh())

    prio = menu.addMenu("Set priority" if win8 else "Set Priority")
    group = QtGui.QActionGroup(prio)
    current = actions.priority_name(proc.nice)
    for name, nice in actions.PRIORITIES:
        act = prio.addAction(name)
        act.setCheckable(True)
        act.setChecked(name == current)
        group.addAction(act)

        def set_prio(_checked=False, nice=nice, name=name):
            if win8 or name in ("Realtime", "High"):
                ok = confirm(parent, "Task Manager" if win8 else "Windows Task Manager",
                             'Do you want to change the priority of "{}"?'.format(proc.name),
                             "Changing the priority of certain processes could cause system instability.",
                             "Change priority")
                if not ok:
                    return
            if guarded(parent, "Unable to Change Priority", actions.set_priority, proc.pid, nice):
                refresh()

        act.triggered.connect(set_prio)

    if actions.supports_affinity():
        def affinity():
            try:
                current_cpus = actions.get_affinity(proc.pid)
            except Exception as exc:  # noqa: BLE001
                show_error(parent, "Processor Affinity", exc)
                return
            dlg = AffinityDialog(proc.name, current_cpus, psutil.cpu_count() or 1, parent)
            if dlg.exec():
                guarded(parent, "Processor Affinity", actions.set_affinity, proc.pid, dlg.selected())

        menu.addAction("Set affinity" if win8 else "Set Affinity...", affinity)

    menu.addSeparator()
    if win8:
        menu.addAction("Open file location", lambda: guarded(parent, "Open file location",
                                                              actions.open_file_location, proc.exe))
    menu.addAction("Properties", lambda: PropertiesDialog(proc, parent).exec())
    return menu


class AboutDialog(QtWidgets.QMessageBox):
    def __init__(self, parent, title):
        super().__init__(parent)
        from .. import __version__
        from ..backend.sysinfo import os_name
        from ..qt import BINDING
        self.setWindowTitle("About " + title)
        self.setIcon(QtWidgets.QMessageBox.Icon.Information)
        self.setText("<b>Task Manager for UNIX</b> {}".format(__version__))
        self.setInformativeText(
            "Windows 7 and Windows 8 style Task Manager layouts for Linux, macOS and BSD.\n\n"
            "Running on {}\nQt binding: {}\npsutil {}".format(os_name(), BINDING, psutil.__version__))
