"""Mapping processes to user facing applications.

Windows decides what an *App* is by looking for top-level windows. On UNIX we
use the same information desktop environments use for their launchers:
freedesktop ``.desktop`` entries on Linux/BSD and ``.app`` bundles on macOS.
"""

import configparser
import glob
import os
import re
import shlex

DESKTOP_DIRS = [
    os.path.expanduser("~/.local/share/applications"),
    "/usr/local/share/applications",
    "/usr/share/applications",
    "/var/lib/flatpak/exports/share/applications",
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    "/var/lib/snapd/desktop/applications",
]

# Wrappers whose first argument is not the real program.
_WRAPPERS = {"env", "flatpak", "snap", "sh", "bash", "exec", "nice", "ionice", "gtk-launch"}

# Programs that are never "apps" even if a .desktop entry points at them.
_NOT_APPS = {"sh", "bash", "python", "python3", "perl", "java", "env", "xdg-open"}


class DesktopEntry:
    __slots__ = ("id", "name", "generic", "comment", "icon", "exec_name", "wm_class", "path", "categories")

    def __init__(self, **kw):
        for key in self.__slots__:
            setattr(self, key, kw.get(key, ""))

    def __repr__(self):
        return "DesktopEntry({!r}, exec={!r})".format(self.name, self.exec_name)


def exec_program(exec_line):
    """Return the basename of the program a ``Exec=`` line launches."""
    if not exec_line:
        return ""
    cleaned = re.sub(r"%[a-zA-Z]", "", exec_line)
    try:
        parts = shlex.split(cleaned)
    except ValueError:
        parts = cleaned.split()
    idx = 0
    while idx < len(parts):
        token = parts[idx]
        base = os.path.basename(token)
        if "=" in token and not token.startswith("/"):
            idx += 1  # VAR=value
        elif token.startswith("-"):
            idx += 1  # wrapper option
        elif base == "flatpak":
            # flatpak run [options] org.app.Id
            rest = [p for p in parts[idx + 1:] if not p.startswith("-") and p != "run"]
            return rest[0].split(".")[-1].lower() if rest else ""
        elif base in _WRAPPERS:
            idx += 1
        else:
            return base
    return ""


def parse_desktop_file(path):
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError, OSError):
        return None
    if not parser.has_section("Desktop Entry"):
        return None
    sec = parser["Desktop Entry"]
    if sec.get("Type", "Application") != "Application":
        return None
    if sec.get("NoDisplay", "false").lower() == "true" or sec.get("Hidden", "false").lower() == "true":
        return None
    exec_name = exec_program(sec.get("Exec", ""))
    if not exec_name or exec_name in _NOT_APPS:
        return None
    return DesktopEntry(
        id=os.path.basename(path)[: -len(".desktop")],
        name=sec.get("Name", exec_name),
        generic=sec.get("GenericName", ""),
        comment=sec.get("Comment", ""),
        icon=sec.get("Icon", ""),
        exec_name=exec_name,
        wm_class=sec.get("StartupWMClass", ""),
        path=path,
        categories=sec.get("Categories", ""),
    )


class AppRegistry:
    """Index of installed applications keyed by the names a process may have."""

    def __init__(self, dirs=None):
        self.by_key = {}
        self.entries = []
        for directory in dirs if dirs is not None else DESKTOP_DIRS:
            for path in sorted(glob.glob(os.path.join(directory, "*.desktop"))):
                entry = parse_desktop_file(path)
                if entry is None:
                    continue
                self.entries.append(entry)
                for key in (entry.exec_name, entry.wm_class, entry.id.split(".")[-1]):
                    key = (key or "").lower()
                    if key and key not in self.by_key:
                        self.by_key[key] = entry

    def lookup(self, name, exe, cmdline0):
        """Return ``(app_id, display_name, description, icon)`` or ``None``."""
        if exe and ".app/Contents/MacOS/" in exe:
            bundle = exe.split(".app/Contents/MacOS/")[0]
            app = os.path.basename(bundle)
            return ("bundle:" + bundle, app, app, "")
        for candidate in (os.path.basename(exe or ""), os.path.basename(cmdline0 or ""), name or ""):
            entry = self.by_key.get(candidate.lower())
            if entry is not None:
                return (entry.id, entry.name, entry.generic or entry.comment or entry.name, entry.icon)
        return None
