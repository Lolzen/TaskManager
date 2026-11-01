"""Persistent per-application resource history (Windows 8 *App history*).

Windows keeps the usage of the last 30 days; we accumulate CPU time and disk
I/O per application while Task Manager is running and store it in
``$XDG_DATA_HOME/taskmanager/app_history.json``.
"""

import json
import os
import time

from .sampler import KIND_APP


def default_path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "taskmanager", "app_history.json")


class AppHistory:
    def __init__(self, path=None):
        self.path = path or default_path()
        self.since = time.time()
        self.apps = {}  # app_id -> {"name", "cpu", "read", "write"}
        self._last = {}  # (pid, create_time) -> (cpu_time, read, write)
        self._dirty = False
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.since = float(data.get("since", self.since))
            self.apps = dict(data.get("apps", {}))
        except (OSError, ValueError, TypeError):
            pass

    def save(self):
        if not self._dirty:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"since": self.since, "apps": self.apps}, fh)
            os.replace(tmp, self.path)
            self._dirty = False
        except OSError:
            pass

    def clear(self):
        self.apps = {}
        self.since = time.time()
        self._dirty = True
        self.save()

    def entries(self, all_processes=False):
        """App entries, or per-process-name entries for *Show history for all processes*."""
        kind = "proc" if all_processes else "app"
        return {k: v for k, v in self.apps.items() if v.get("kind", "app") == kind}

    def _add(self, key, name, kind, cpu, read, write):
        entry = self.apps.setdefault(key, {"name": name, "kind": kind, "cpu": 0.0, "read": 0, "write": 0})
        entry["name"] = name
        entry["cpu"] += cpu
        entry["read"] += read
        entry["write"] += write
        self._dirty = True

    def update(self, snapshot):
        """Accumulate the usage that happened since the previous snapshot."""
        current = {}
        for proc in snapshot.procs.values():
            key = (proc.pid, proc.create_time)
            current[key] = (proc.cpu_time, proc.io_read, proc.io_write)
            prev = self._last.get(key)
            if prev is None:
                continue  # only count usage observed while we were running
            cpu = max(0.0, proc.cpu_time - prev[0])
            read = max(0, proc.io_read - prev[1])
            write = max(0, proc.io_write - prev[2])
            if not (cpu or read or write):
                continue
            if proc.kind == KIND_APP and proc.app_id:
                self._add(proc.app_id, proc.app_name, "app", cpu, read, write)
            self._add("proc:" + proc.name, proc.name, "proc", cpu, read, write)
        self._last = current
