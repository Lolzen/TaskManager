"""Tux mode: the extra information Linux exposes beyond what Windows shows.

Per process (``read_proc_extras``): kernel state, scheduling policy, I/O
priority, cgroup/systemd unit, container, OOM score, USS/PSS/swap, open file
descriptors, context switches, page faults, capabilities, seccomp, security
label and more, all from ``/proc/<pid>``.

System wide (``SystemSampler``): load average, pressure stall information,
context switches/interrupts per second, sensors, CPU governor and
vulnerabilities, kernel limits, filesystems, NIC details and disk schedulers.

Every reader takes the ``/proc`` and ``/sys`` roots as parameters so it can be
tested against fake trees, and degrades to empty values on non-Linux systems.
"""

import os
import platform
import re
from dataclasses import dataclass, field

import psutil

from . import sysinfo

STATES = {"R": "Running", "S": "Sleeping", "D": "Disk sleep", "Z": "Zombie", "T": "Stopped",
          "t": "Tracing stop", "X": "Dead", "I": "Idle", "P": "Parked", "W": "Waking", "K": "Wakekill"}
POLICIES = {0: "Normal", 1: "FIFO", 2: "Round robin", 3: "Batch", 5: "Idle", 6: "Deadline"}
IOPRIO_CLASSES = {0: "None", 1: "Realtime", 2: "Best effort", 3: "Idle"}
SECCOMP = {"0": "Disabled", "1": "Strict", "2": "Filter"}
FULL_CAPS = 0x1FFFFFFFFF  # every capability up to CAP_CHECKPOINT_RESTORE (40)


def _read(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return default


def _kib(text):
    match = re.match(r"\s*(\d+)", text or "")
    return int(match.group(1)) * 1024 if match else 0


# -- per process ---------------------------------------------------------------

@dataclass
class ProcExtras:
    state: str = ""
    policy: str = ""
    rt_priority: int = 0
    io_priority: str = ""
    cgroup: str = ""
    unit: str = ""
    container: str = ""
    oom_score: int = 0
    oom_adj: int = 0
    uss: int = 0
    pss: int = 0
    swap: int = 0
    vms: int = 0
    fds: int = -1
    ctx_voluntary: int = 0
    ctx_involuntary: int = 0
    minor_faults: int = 0
    major_faults: int = 0
    last_cpu: int = -1
    session: int = 0
    pgrp: int = 0
    capabilities: str = ""
    seccomp: str = ""
    no_new_privs: bool = False
    label: str = ""
    cwd: str = ""


def parse_stat(text):
    """Fields of ``/proc/<pid>/stat`` after the command name, keyed by name."""
    if ")" not in text:
        return {}
    fields = text[text.rindex(")") + 2:].split()
    if len(fields) < 39:
        return {"state": fields[0]} if fields else {}

    def num(i):
        try:
            return int(fields[i])
        except (IndexError, ValueError):
            return 0

    return {"state": fields[0], "pgrp": num(2), "session": num(3), "minflt": num(7), "majflt": num(9),
            "vsize": num(20), "processor": num(36), "rt_priority": num(37), "policy": num(38)}


def parse_status(text):
    values = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            values[key.strip()] = value.strip()
    return values


def describe_caps(hex_mask):
    try:
        mask = int(hex_mask, 16)
    except (TypeError, ValueError):
        return ""
    if mask == 0:
        return "None"
    if mask & FULL_CAPS == FULL_CAPS:
        return "All"
    return "{} capabilities".format(bin(mask).count("1"))


def unit_from_cgroup(path):
    """``/user.slice/user-1000.slice/user@1000.service/app.slice/app-firefox.scope`` -> ``app-firefox.scope``."""
    for part in reversed([p for p in path.split("/") if p]):
        if part.endswith((".service", ".scope")):
            return part
    return ""


def container_from_cgroup(path, flatpak=False):
    if flatpak:
        return "Flatpak"
    patterns = (("snap.", "Snap"), ("docker-", "Docker"), ("/docker/", "Docker"), ("libpod-", "Podman"),
                ("/lxc", "LXC"), ("machine.slice", "systemd-nspawn"), ("kubepods", "Kubernetes"))
    for needle, name in patterns:
        if needle in path:
            return name
    return ""


def parse_cgroup(text):
    """Prefer the unified (v2) hierarchy, fall back to the systemd v1 one."""
    v1 = ""
    for line in text.splitlines():
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        if parts[0] == "0" and parts[1] == "":
            if parts[2] != "/" or not v1:
                return parts[2]
        elif parts[1] == "name=systemd":
            v1 = parts[2]
    return v1


def read_proc_extras(pid, proc_root="/proc"):
    base = os.path.join(proc_root, str(pid))
    ex = ProcExtras()
    stat = parse_stat(_read(os.path.join(base, "stat")))
    if stat:
        ex.state = STATES.get(stat["state"], stat["state"])
        ex.pgrp, ex.session = stat.get("pgrp", 0), stat.get("session", 0)
        ex.minor_faults, ex.major_faults = stat.get("minflt", 0), stat.get("majflt", 0)
        ex.vms = stat.get("vsize", 0)
        ex.last_cpu = stat.get("processor", -1)
        ex.rt_priority = stat.get("rt_priority", 0)
        ex.policy = POLICIES.get(stat.get("policy", 0), str(stat.get("policy", "")))
    status = parse_status(_read(os.path.join(base, "status")))
    if status:
        ex.ctx_voluntary = int(status.get("voluntary_ctxt_switches", "0") or 0)
        ex.ctx_involuntary = int(status.get("nonvoluntary_ctxt_switches", "0") or 0)
        ex.capabilities = describe_caps(status.get("CapEff"))
        ex.seccomp = SECCOMP.get(status.get("Seccomp", ""), "")
        ex.no_new_privs = status.get("NoNewPrivs") == "1"
        ex.swap = _kib(status.get("VmSwap", ""))
    rollup = parse_status(_read(os.path.join(base, "smaps_rollup")))
    if rollup:
        ex.pss = _kib(rollup.get("Pss", ""))
        ex.uss = _kib(rollup.get("Private_Clean", "")) + _kib(rollup.get("Private_Dirty", ""))
        ex.swap = _kib(rollup.get("Swap", "")) or ex.swap
    ex.cgroup = parse_cgroup(_read(os.path.join(base, "cgroup")))
    ex.unit = unit_from_cgroup(ex.cgroup)
    ex.container = container_from_cgroup(ex.cgroup, os.path.exists(os.path.join(base, "root", ".flatpak-info")))
    try:
        ex.oom_score = int(_read(os.path.join(base, "oom_score"), "0").strip() or 0)
        ex.oom_adj = int(_read(os.path.join(base, "oom_score_adj"), "0").strip() or 0)
    except ValueError:
        pass
    try:
        ex.fds = len(os.listdir(os.path.join(base, "fd")))
    except OSError:
        ex.fds = -1
    label = _read(os.path.join(base, "attr", "current")).strip("\x00\n ")
    ex.label = label
    try:
        ex.cwd = os.readlink(os.path.join(base, "cwd"))
    except OSError:
        ex.cwd = ""
    return ex


def io_priority(pid):
    if not hasattr(psutil.Process, "ionice"):
        return ""
    try:
        value = psutil.Process(pid).ionice()
    except (psutil.Error, OSError):
        return ""
    cls = IOPRIO_CLASSES.get(int(value.ioclass), str(value.ioclass))
    return "{} ({})".format(cls, value.value) if int(value.ioclass) in (1, 2) else cls


# -- system wide ---------------------------------------------------------------

@dataclass
class SystemExtras:
    loadavg: tuple = (0.0, 0.0, 0.0)
    running_tasks: str = ""
    pressure: dict = field(default_factory=dict)  # "cpu some" -> (avg10, avg60, avg300)
    ctx_switches_ps: float = 0.0
    interrupts_ps: float = 0.0
    soft_interrupts_ps: float = 0.0
    forks_ps: float = 0.0
    temperatures: list = field(default_factory=list)  # (chip, label, current, high, critical)
    fans: list = field(default_factory=list)  # (chip, label, rpm)
    battery: object = None
    cpu_freqs: list = field(default_factory=list)  # MHz per logical CPU
    governor: str = ""
    meminfo: dict = field(default_factory=dict)
    file_handles: tuple = (0, 0)
    filesystems: list = field(default_factory=list)  # (mount, device, fstype, used, total)
    nics: list = field(default_factory=list)  # (name, mac, mtu, duplex, errin, errout, dropin, dropout)
    schedulers: dict = field(default_factory=dict)  # disk -> scheduler
    static: dict = field(default_factory=dict)  # slow-changing facts, see static_info()

    @property
    def cpu_temperature(self):
        """Hottest CPU package/core sensor, or ``None``."""
        cpu = [t for t in self.temperatures if t[0] in ("coretemp", "k10temp", "zenpower", "cpu_thermal",
                                                         "acpitz", "cpu-thermal", "soc_thermal")]
        pool = cpu or self.temperatures
        return max((t[2] for t in pool), default=None)


def parse_pressure(text):
    result = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        values = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        try:
            result[parts[0]] = (float(values["avg10"]), float(values["avg60"]), float(values["avg300"]))
        except (KeyError, ValueError):
            continue
    return result


def parse_scheduler(text):
    match = re.search(r"\[([^\]]+)\]", text)
    return match.group(1) if match else text.strip()


def _vulnerabilities(sys_root):
    directory = os.path.join(sys_root, "devices", "system", "cpu", "vulnerabilities")
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return {}
    return {name.replace("_", " ").capitalize(): _read(os.path.join(directory, name)).strip() for name in names}


def static_info(proc_root="/proc", sys_root="/sys"):
    """Facts that do not change while Task Manager runs."""
    session = os.environ.get("XDG_SESSION_TYPE") or ("wayland" if os.environ.get("WAYLAND_DISPLAY") else
                                                     "x11" if os.environ.get("DISPLAY") else "none")
    cgroup = "v2 (unified)" if os.path.exists(os.path.join(sys_root, "fs", "cgroup", "cgroup.controllers")) \
        else "v1" if os.path.isdir(os.path.join(sys_root, "fs", "cgroup")) else "N/A"
    init = _read(os.path.join(proc_root, "1", "comm")).strip() or \
        os.path.basename(os.path.realpath(os.path.join(proc_root, "1", "exe")))
    return {
        "Kernel": "{} {}".format(platform.system(), platform.release()),
        "Kernel build": platform.version(),
        "Distribution": sysinfo.os_name(),
        "Architecture": platform.machine(),
        "Hostname": platform.node(),
        "Init system": init or "N/A",
        "Desktop": os.environ.get("XDG_CURRENT_DESKTOP", "N/A"),
        "Display server": session,
        "cgroups": cgroup,
        "PID max": _read(os.path.join(proc_root, "sys", "kernel", "pid_max")).strip() or "N/A",
        "Threads max": _read(os.path.join(proc_root, "sys", "kernel", "threads-max")).strip() or "N/A",
        "inotify watches max": _read(os.path.join(proc_root, "sys", "fs", "inotify", "max_user_watches")).strip()
        or "N/A",
        "Swappiness": _read(os.path.join(proc_root, "sys", "vm", "swappiness")).strip() or "N/A",
        "Overcommit": {"0": "Heuristic", "1": "Always", "2": "Never"}.get(
            _read(os.path.join(proc_root, "sys", "vm", "overcommit_memory")).strip(), "N/A"),
        "vulnerabilities": _vulnerabilities(sys_root),
    }


class SystemSampler:
    FS_EVERY = 10  # filesystems are re-read every N samples

    def __init__(self, proc_root="/proc", sys_root="/sys"):
        self.proc_root, self.sys_root = proc_root, sys_root
        self._static = None
        self._prev_stats = None
        self._prev_forks = None
        self._tick = 0
        self._filesystems = []

    def _forks(self):
        match = re.search(r"^processes\s+(\d+)", _read(os.path.join(self.proc_root, "stat")), re.M)
        return int(match.group(1)) if match else None

    def sample(self, dt):
        if self._static is None:
            self._static = static_info(self.proc_root, self.sys_root)
        ex = SystemExtras(static=self._static)
        try:
            ex.loadavg = os.getloadavg()
        except (OSError, AttributeError):
            pass
        parts = _read(os.path.join(self.proc_root, "loadavg")).split()
        ex.running_tasks = parts[3] if len(parts) > 3 else ""
        for resource in ("cpu", "memory", "io"):
            for kind, values in parse_pressure(_read(os.path.join(self.proc_root, "pressure", resource))).items():
                ex.pressure["{} {}".format(resource, kind)] = values

        stats = psutil.cpu_stats()
        forks = self._forks()
        if self._prev_stats is not None and dt > 0:
            ex.ctx_switches_ps = max(0, stats.ctx_switches - self._prev_stats.ctx_switches) / dt
            ex.interrupts_ps = max(0, stats.interrupts - self._prev_stats.interrupts) / dt
            ex.soft_interrupts_ps = max(0, stats.soft_interrupts - self._prev_stats.soft_interrupts) / dt
            if forks is not None and self._prev_forks is not None:
                ex.forks_ps = max(0, forks - self._prev_forks) / dt
        self._prev_stats, self._prev_forks = stats, forks

        sensors = getattr(psutil, "sensors_temperatures", None)
        try:
            temps = sensors() if sensors else {}
        except (OSError, RuntimeError):
            temps = {}
        for chip, entries in sorted(temps.items()):
            for idx, entry in enumerate(entries):
                ex.temperatures.append((chip, entry.label or "{} {}".format(chip, idx + 1), entry.current,
                                        entry.high, entry.critical))
        fans = getattr(psutil, "sensors_fans", None)
        try:
            for chip, entries in sorted((fans() if fans else {}).items()):
                for idx, entry in enumerate(entries):
                    ex.fans.append((chip, entry.label or "Fan {}".format(idx + 1), entry.current))
        except (OSError, RuntimeError):
            pass
        battery = getattr(psutil, "sensors_battery", None)
        try:
            ex.battery = battery() if battery else None
        except (OSError, RuntimeError):
            ex.battery = None

        try:
            ex.cpu_freqs = [f.current for f in psutil.cpu_freq(percpu=True) or []]
        except (OSError, NotImplementedError, AttributeError):
            ex.cpu_freqs = []
        ex.governor = _read(os.path.join(self.sys_root, "devices", "system", "cpu", "cpu0", "cpufreq",
                                         "scaling_governor")).strip()
        ex.meminfo = sysinfo.parse_meminfo(_read(os.path.join(self.proc_root, "meminfo")))
        handles = _read(os.path.join(self.proc_root, "sys", "fs", "file-nr")).split()
        if len(handles) >= 3:
            ex.file_handles = (int(handles[0]), int(handles[2]))

        if self._tick % self.FS_EVERY == 0:
            self._filesystems = self._read_filesystems()
        self._tick += 1
        ex.filesystems = self._filesystems

        try:
            counters = psutil.net_io_counters(pernic=True)
            stats_if = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
        except (OSError, RuntimeError):
            counters, stats_if, addrs = {}, {}, {}
        duplex = {getattr(psutil, "NIC_DUPLEX_FULL", 2): "Full", getattr(psutil, "NIC_DUPLEX_HALF", 1): "Half"}
        link = getattr(psutil, "AF_LINK", None)
        for name in sorted(counters):
            c, st = counters[name], stats_if.get(name)
            mac = next((a.address for a in addrs.get(name, []) if a.family == link), "")
            ex.nics.append((name, mac, st.mtu if st else 0, duplex.get(st.duplex, "Unknown") if st else "",
                            c.errin, c.errout, c.dropin, c.dropout))
        block = os.path.join(self.sys_root, "block")
        try:
            disks = sorted(os.listdir(block))
        except OSError:
            disks = []
        for disk in disks:
            if disk.startswith(("loop", "ram")):
                continue
            sched = _read(os.path.join(block, disk, "queue", "scheduler"))
            if sched:
                ex.schedulers[disk] = parse_scheduler(sched)
        return ex

    @staticmethod
    def _read_filesystems():
        result = []
        try:
            parts = psutil.disk_partitions(all=False)
        except OSError:
            return result
        for part in parts:
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            result.append((part.mountpoint, part.device, part.fstype, usage.used, usage.total))
        return result
