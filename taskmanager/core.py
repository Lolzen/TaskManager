"""Qt glue shared by both layouts: background sampling and async helpers."""

import contextlib
import sys
import traceback

from .backend.sampler import Sampler
from .qt import QtCore, Signal, Slot, is_alive

# Windows' *Update speed* menu
SPEEDS = {"High": 500, "Normal": 1000, "Low": 4000, "Paused": 0}


class _SamplerWorker(QtCore.QObject):
    sampled = Signal(object)
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.sampler = None
        self.timer = None
        self.tux = False

    @Slot()
    def start(self):
        self.sampler = Sampler()
        self.sampler.tux = self.tux
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.tick()  # prime the counters so the first real sample has rates
        QtCore.QTimer.singleShot(250, self.tick)

    @Slot(int)
    def set_interval(self, msec):
        if self.timer is None:
            return
        if msec <= 0:
            self.timer.stop()
        else:
            self.timer.start(msec)

    @Slot(bool)
    def set_tux(self, enabled):
        self.tux = enabled
        if self.sampler is not None:
            self.sampler.tux = enabled

    @Slot()
    def shutdown(self):
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None

    @Slot()
    def tick(self):
        try:
            snap = self.sampler.sample()
        except Exception:  # noqa: BLE001 - never kill the sampling thread
            self.failed.emit(traceback.format_exc())
            return
        if snap.interval > 0 and self.timer is not None:
            self.sampled.emit(snap)


class SamplerThread(QtCore.QObject):
    """Owns the sampling thread; emits ``snapshot`` on the GUI thread."""

    snapshot = Signal(object)
    _set_interval = Signal(int)
    _set_tux = Signal(bool)
    _tick = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.last = None
        self.speed = "Normal"
        self._thread = QtCore.QThread(self)
        self._worker = _SamplerWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start)
        self._worker.sampled.connect(self._on_sample)
        self._worker.failed.connect(sys.stderr.write)
        self._set_interval.connect(self._worker.set_interval)
        self._set_tux.connect(self._worker.set_tux)
        self._tick.connect(self._worker.tick)
        self._thread.start()
        self.set_speed(self.speed)

    def _on_sample(self, snap):
        self.last = snap
        self.snapshot.emit(snap)

    def set_speed(self, name):
        self.speed = name
        self._set_interval.emit(SPEEDS[name])

    def set_tux(self, enabled):
        self._set_tux.emit(enabled)

    def refresh_now(self):
        self._tick.emit()

    def stop(self):
        QtCore.QMetaObject.invokeMethod(self._worker, "shutdown",
                                        QtCore.Qt.ConnectionType.BlockingQueuedConnection)
        self._thread.quit()
        self._thread.wait(3000)


class _Relay(QtCore.QObject):
    done = Signal(object, object)


class _Task(QtCore.QRunnable):
    def __init__(self, fn, relay):
        super().__init__()
        self.fn, self.relay = fn, relay

    def run(self):
        try:
            result, error = self.fn(), None
        except Exception as exc:  # noqa: BLE001 - reported to the callback
            result, error = None, exc
        # When the application quits while fn() runs, interpreter teardown can
        # delete the relay first. PyQt6 aborts on an exception escaping run(),
        # and there is nobody left to deliver the result to anyway.
        try:
            if is_alive(self.relay):
                self.relay.done.emit(result, error)
        except RuntimeError:
            pass


_relays = set()


def run_async(fn, callback, owner=None):
    """Run ``fn()`` on the thread pool and call ``callback(result, error)``.

    When ``owner`` (the widget the callback updates) has been deleted by the
    time ``fn`` returns, e.g. because the user switched layouts, the callback
    is dropped. PyQt6 aborts the whole application on an exception in a slot,
    so touching the deleted widget is not an option.
    """
    relay = _Relay()
    _relays.add(relay)

    def finish(result, error):
        _relays.discard(relay)
        if owner is not None and not is_alive(owner):
            return
        callback(result, error)

    relay.done.connect(finish, QtCore.Qt.ConnectionType.QueuedConnection)
    QtCore.QThreadPool.globalInstance().start(_Task(fn, relay))


@contextlib.contextmanager
def bulk_update(tree):
    """Suspend sorting/painting while many items of a tree change."""
    sorting = tree.isSortingEnabled()
    tree.setUpdatesEnabled(False)
    tree.setSortingEnabled(False)
    try:
        yield
    finally:
        tree.setSortingEnabled(sorting)
        tree.setUpdatesEnabled(True)
