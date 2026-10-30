"""Startup programs (Windows 8 *Startup* tab).

Linux/BSD: XDG autostart entries. Disabling an entry follows the XDG spec by
writing a per-user override with ``Hidden=true`` into ``~/.config/autostart``.
macOS: LaunchAgents property lists (listed read-only).
"""

import configparser
import glob
import os
import plistlib
import shutil
import subprocess
from dataclasses import dataclass

from . import sysinfo


def _config_home():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def autostart_dirs():
    system = os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":")
    return [os.path.join(_config_home(), "autostart")] + [os.path.join(d, "autostart") for d in system]


@dataclass
class StartupItem:
    id: str
    name: str
    publisher: str = ""
    enabled: bool = True
    command: str = ""
    path: str = ""
    impact: str = "Not measured"
    editable: bool = True
    source: str = ""  # Windows 10 *Startup type*
    kind: str = "xdg"  # xdg / launchd / systemd

    @property
    def status(self):
        return "Enabled" if self.enabled else "Disabled"


def _read_desktop(path):
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError, OSError):
        return None
    if not parser.has_section("Desktop Entry"):
        return None
    return parser


def _is_enabled(sec):
    if sec.get("Hidden", "false").strip().lower() == "true":
        return False
    if sec.get("X-GNOME-Autostart-enabled", "true").strip().lower() == "false":
        return False
    return True


def list_xdg(dirs=None):
    items = {}
    dirs = dirs if dirs is not None else autostart_dirs()
    for directory in reversed(dirs):
        source = "Autostart (user)" if directory == dirs[0] else "Autostart (system)"
        # later (user) directories override earlier (system) ones
        for path in sorted(glob.glob(os.path.join(directory, "*.desktop"))):
            parser = _read_desktop(path)
            if parser is None:
                continue
            sec = parser["Desktop Entry"]
            item_id = os.path.basename(path)
            base = items.get(item_id)
            items[item_id] = StartupItem(
                id=item_id,
                name=sec.get("Name", base.name if base else item_id[:-8]),
                publisher=sec.get("X-GNOME-Bugzilla-Product", "") or sec.get("X-KDE-PluginInfo-Author", "")
                or (base.publisher if base else ""),
                enabled=_is_enabled(sec),
                command=sec.get("Exec", base.command if base else ""),
                path=path,
                source=source if base is None else base.source,
            )
    return sorted(items.values(), key=lambda i: i.name.lower())


def set_xdg_enabled(item, enabled, user_dir=None):
    """Enable/disable an autostart entry via a user override file."""
    user_dir = user_dir or autostart_dirs()[0]
    os.makedirs(user_dir, exist_ok=True)
    target = os.path.join(user_dir, item.id)
    parser = _read_desktop(target) if os.path.exists(target) else None
    if parser is None:
        parser = _read_desktop(item.path) if item.path and os.path.exists(item.path) else None
    if parser is None:
        parser = configparser.RawConfigParser(strict=False, interpolation=None)
        parser.optionxform = str
        parser.add_section("Desktop Entry")
        parser["Desktop Entry"]["Type"] = "Application"
        parser["Desktop Entry"]["Name"] = item.name
        parser["Desktop Entry"]["Exec"] = item.command
    sec = parser["Desktop Entry"]
    sec["Hidden"] = "false" if enabled else "true"
    if "X-GNOME-Autostart-enabled" in sec:
        sec["X-GNOME-Autostart-enabled"] = "true" if enabled else "false"
    with open(target, "w", encoding="utf-8") as fh:
        parser.write(fh, space_around_delimiters=False)
    item.enabled = enabled
    item.path = target


def list_launch_agents():
    items = []
    dirs = [os.path.expanduser("~/Library/LaunchAgents"), "/Library/LaunchAgents"]
    for directory in dirs:
        for path in sorted(glob.glob(os.path.join(directory, "*.plist"))):
            try:
                with open(path, "rb") as fh:
                    data = plistlib.load(fh)
            except Exception:  # noqa: BLE001 - malformed plists are skipped
                continue
            label = data.get("Label", os.path.basename(path)[:-6])
            program = data.get("Program") or " ".join(data.get("ProgramArguments", []))
            items.append(StartupItem(
                id=label,
                name=label.split(".")[-1],
                publisher=".".join(label.split(".")[:2]),
                enabled=not data.get("Disabled", False),
                command=program,
                path=path,
                editable=False,
                source="LaunchAgent",
                kind="launchd",
            ))
    return sorted(items, key=lambda i: i.name.lower())


def parse_user_unit_files(text):
    """``systemctl --user list-unit-files`` -> StartupItems for enabled/disabled units."""
    items = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].endswith(".service") or "@" in parts[0]:
            continue
        if parts[1] not in ("enabled", "disabled"):
            continue  # static, indirect, generated, alias... cannot be toggled
        name = parts[0][: -len(".service")]
        items.append(StartupItem(id="systemd:" + parts[0], name=name, publisher="systemd user unit",
                                 enabled=parts[1] == "enabled", command="systemctl --user start " + parts[0],
                                 path=parts[0], source="systemd --user", kind="systemd"))
    return items


def list_systemd_user():
    """Tux mode: systemd user services also start with the session."""
    if not shutil.which("systemctl"):
        return []
    try:
        out = subprocess.run(["systemctl", "--user", "list-unit-files", "--type=service", "--no-legend",
                              "--no-pager"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_user_unit_files(out.stdout) if out.returncode == 0 else []


def list_startup(tux=False):
    if sysinfo.IS_MAC:
        return list_launch_agents()
    items = list_xdg()
    if tux:
        items += list_systemd_user()
    return items


def set_enabled(item, enabled):
    if not item.editable:
        raise PermissionError("This startup item cannot be changed from Task Manager.")
    if item.kind == "systemd":
        out = subprocess.run(["systemctl", "--user", "enable" if enabled else "disable", item.path],
                             capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            raise OSError(out.stderr.strip() or "systemctl failed")
        item.enabled = enabled
        return
    set_xdg_enabled(item, enabled)
