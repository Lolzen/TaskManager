"""Qt binding shim.

PySide6 is preferred and PyQt6 is the fallback, so the application runs with
whichever modern Qt binding the distribution ships (Ubuntu 24.04, for example,
only packages PyQt6). Set ``TASKMANAGER_QT=pyqt6`` or ``pyside6`` to force one.
"""

import os

_WANTED = os.environ.get("TASKMANAGER_QT", "").lower()


def _pyside6():
    global QtCore, QtGui, QtWidgets, Qt, Signal, Slot, BINDING
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt, Signal, Slot
    BINDING = "PySide6"


def _pyqt6():
    global QtCore, QtGui, QtWidgets, Qt, Signal, Slot, BINDING
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtCore import Qt
    from PyQt6.QtCore import pyqtSignal as Signal
    from PyQt6.QtCore import pyqtSlot as Slot
    BINDING = "PyQt6"


_ORDER = [_pyqt6, _pyside6] if _WANTED == "pyqt6" else [_pyside6, _pyqt6]
_errors = []
for _loader in _ORDER:
    try:
        _loader()
        break
    except ImportError as _error:  # pragma: no cover - depends on the host system
        _errors.append("{}: {}".format(_loader.__name__.strip("_"), _error))
else:  # pragma: no cover
    raise ImportError("Task Manager needs PySide6 or PyQt6 ({})".format("; ".join(_errors)))
