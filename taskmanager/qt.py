"""Qt binding shim.

PySide6 is preferred; PyQt6 is used as a fallback so the application runs with
whichever modern Qt binding the distribution ships.
"""

try:
    from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
    from PySide6.QtCore import Qt, Signal, Slot  # noqa: F401

    BINDING = "PySide6"
except ImportError:  # pragma: no cover - depends on the host system
    from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401
    from PyQt6.QtCore import Qt  # noqa: F401
    from PyQt6.QtCore import pyqtSignal as Signal  # noqa: F401
    from PyQt6.QtCore import pyqtSlot as Slot  # noqa: F401

    BINDING = "PyQt6"
