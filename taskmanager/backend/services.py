"""Service enumeration and control for systemd (Linux) and launchd (macOS)."""

import os
import shutil
import subprocess
from dataclasses import dataclass

from . import sysinfo


@dataclass
class Service:
    name: str
    description: str = ""
    status: str = "Stopped"  # "Running" / "Stopped" like Windows
    pid: int = 0
    group: str = ""
    detail: str = ""  # backend specific state, e.g. "active (running)"
    startup: str = ""  # enabled / disabled / static ...


class ServiceError(RuntimeError):
    pass


def _run(cmd, timeout=10):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ServiceError(str(exc)) from exc
    return out


def parse_systemctl_show(text):
    """Parse ``systemctl show`` output for many units into ``Service`` objects."""
    services = []
    for block in text.strip().split("\n\n"):
        props = {}
        for line in block.splitlines():
            key, sep, value = line.partition("=")
            if sep:
                props[key] = value
        unit = props.get("Id", "")
        if not unit.endswith(".service") or props.get("LoadState") == "not-found":
            continue
        active, sub = props.get("ActiveState", ""), props.get("SubState", "")
        pid = props.get("MainPID", "0")
        slice_name = props.get("Slice", "")
        services.append(Service(
            name=unit[: -len(".service")],
            description=props.get("Description", ""),
            status="Running" if active in ("active", "reloading", "activating") else "Stopped",
            pid=int(pid) if pid.isdigit() else 0,
            group=slice_name[: -len(".slice")] if slice_name.endswith(".slice") else slice_name,
            detail="{} ({})".format(active, sub) if sub else active,
            startup=props.get("UnitFileState", ""),
        ))
    services.sort(key=lambda s: s.name.lower())
    return services


def parse_launchctl_list(text):
    services = []
    for line in text.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) != 3:
            continue
        pid, status, label = parts
        services.append(Service(
            name=label,
            description=label,
            status="Running" if pid.isdigit() else "Stopped",
            pid=int(pid) if pid.isdigit() else 0,
            group=label.rsplit(".", 1)[0] if "." in label else "",
            detail="exit status " + status,
        ))
    services.sort(key=lambda s: s.name.lower())
    return services


def backend_name():
    if shutil.which("systemctl") and os.path.isdir("/run/systemd/system"):
        return "systemd"
    if sysinfo.IS_MAC and shutil.which("launchctl"):
        return "launchd"
    return None


_PROPS = "Id,Description,LoadState,ActiveState,SubState,MainPID,Slice,UnitFileState"


def list_services():
    """Return all services, or raise ``ServiceError`` if none can be listed."""
    backend = backend_name()
    if backend == "systemd":
        out = _run(["systemctl", "list-units", "--type=service", "--all", "--plain",
                    "--no-legend", "--no-pager"])
        units = [line.split()[0] for line in out.stdout.splitlines() if line.split()]
        files = _run(["systemctl", "list-unit-files", "--type=service", "--no-legend", "--no-pager"])
        for line in files.stdout.splitlines():
            parts = line.split()
            if parts and "@" not in parts[0] and parts[0] not in units:
                units.append(parts[0])
        units = [u for u in units if u.endswith(".service")]
        if not units:
            return []
        show = _run(["systemctl", "show", "--no-pager", "-p", _PROPS] + units, timeout=30)
        return parse_systemctl_show(show.stdout)
    if backend == "launchd":
        return parse_launchctl_list(_run(["launchctl", "list"]).stdout)
    raise ServiceError("No supported service manager (systemd or launchd) is running.")


def _privileged(cmd):
    if hasattr(os, "geteuid") and os.geteuid() != 0 and shutil.which("pkexec"):
        return ["pkexec"] + cmd
    return cmd


def control(service, action):
    """``action`` is one of ``start``, ``stop`` or ``restart``."""
    backend = backend_name()
    if backend == "systemd":
        cmd = _privileged(["systemctl", action, service.name + ".service"])
    elif backend == "launchd":
        if action == "restart":
            cmd = ["launchctl", "kickstart", "-k", "gui/{}/{}".format(os.getuid(), service.name)]
        else:
            cmd = ["launchctl", action, service.name]
    else:
        raise ServiceError("No supported service manager found.")
    out = _run(cmd, timeout=120)
    if out.returncode != 0:
        raise ServiceError((out.stderr or out.stdout).strip() or "Command failed: " + " ".join(cmd))


def services_by_pid(services):
    mapping = {}
    for svc in services:
        if svc.pid:
            mapping.setdefault(svc.pid, []).append(svc.name)
    return mapping
