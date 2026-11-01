"""Tux mode widgets and column definitions shared by every layout."""

import datetime

from ..backend.formatting import fmt_bytes, fmt_kb, fmt_uptime
from ..core import bulk_update
from ..qt import QtWidgets
from .tree import LEFT, RIGHT, ItemSync, make_tree, set_cell


def _x(attr, fmt=str, missing=""):
    """Text getter for a ``ProcExtras`` attribute that tolerates ``proc.tux is None``."""
    def get(proc):
        extras = proc.tux
        if extras is None:
            return missing
        value = getattr(extras, attr)
        return fmt(value) if value not in (None, "") else missing
    return get


def _s(attr, default=0):
    def get(proc):
        return getattr(proc.tux, attr) if proc.tux is not None else default
    return get


def _fds(value):
    return "{:,}".format(value) if value >= 0 else "Access denied"


# (title, text(proc), sort(proc) or None, align, width, shown by default)
PROC_COLUMNS = [
    ("State", _x("state"), None, LEFT, 80, True),
    ("Parent PID", lambda p: str(p.ppid), lambda p: p.ppid, RIGHT, 70, False),
    ("Nice", lambda p: str(p.nice), lambda p: p.nice, RIGHT, 45, False),
    ("Scheduling policy", _x("policy"), None, LEFT, 110, False),
    ("I/O priority", _x("io_priority"), None, LEFT, 100, False),
    ("systemd unit", _x("unit"), None, LEFT, 180, True),
    ("cgroup", _x("cgroup"), None, LEFT, 260, False),
    ("Container", _x("container"), None, LEFT, 80, False),
    ("OOM score", _x("oom_score"), _s("oom_score"), RIGHT, 75, True),
    ("OOM adjust", _x("oom_adj"), _s("oom_adj"), RIGHT, 75, False),
    ("Memory (USS)", _x("uss", fmt_kb), _s("uss"), RIGHT, 100, True),
    ("Memory (PSS)", _x("pss", fmt_kb), _s("pss"), RIGHT, 100, False),
    ("Swap", _x("swap", fmt_kb), _s("swap"), RIGHT, 80, False),
    ("Virtual memory", _x("vms", fmt_kb), _s("vms"), RIGHT, 110, False),
    ("Open files", _x("fds", _fds), _s("fds", -1), RIGHT, 75, True),
    ("Context switches", lambda p: "{:,}".format(p.tux.ctx_voluntary + p.tux.ctx_involuntary) if p.tux else "",
     lambda p: p.tux.ctx_voluntary + p.tux.ctx_involuntary if p.tux else 0, RIGHT, 110, False),
    ("Page faults (major)", _x("major_faults", "{:,}".format), _s("major_faults"), RIGHT, 115, False),
    ("Page faults (minor)", _x("minor_faults", "{:,}".format), _s("minor_faults"), RIGHT, 115, False),
    ("Last CPU", _x("last_cpu"), _s("last_cpu", -1), RIGHT, 65, False),
    ("Session ID", _x("session"), _s("session"), RIGHT, 75, False),
    ("Process group", _x("pgrp"), _s("pgrp"), RIGHT, 90, False),
    ("TTY", lambda p: p.terminal.replace("/dev/", ""), None, LEFT, 60, False),
    ("Capabilities", _x("capabilities"), None, LEFT, 110, False),
    ("Seccomp", _x("seccomp"), None, LEFT, 70, False),
    ("No new privileges", lambda p: ("Yes" if p.tux.no_new_privs else "No") if p.tux else "", None, LEFT, 110,
     False),
    ("Security label", _x("label"), None, LEFT, 150, False),
    ("Working directory", _x("cwd"), None, LEFT, 200, False),
]


def proc_status(proc, fallback):
    """Tux mode shows the real kernel state instead of Windows' Running/Suspended."""
    return proc.tux.state if proc.tux is not None and proc.tux.state else fallback


# -- performance page extras ----------------------------------------------------------

CPU_KEYS = ["Load average", "CPU pressure", "Context switches/s", "Interrupts/s", "Governor", "Temperature"]
MEM_KEYS = ["Memory pressure", "Dirty", "Writeback", "Huge pages", "Swappiness", "Overcommit"]
DISK_KEYS = ["I/O scheduler", "I/O pressure"]
NET_KEYS = ["MAC address", "MTU", "Duplex", "Errors (in/out)", "Drops (in/out)"]


def _pressure(ex, resource):
    some = ex.pressure.get(resource + " some")
    if some is None:
        return "N/A"
    full = ex.pressure.get(resource + " full")
    text = "{:.1f}% some".format(some[0])
    if full is not None and resource != "cpu":
        text += ", {:.1f}% full".format(full[0])
    return text


def cpu_values(ex):
    temp = ex.cpu_temperature
    return {
        "Load average": "{:.2f}  {:.2f}  {:.2f}".format(*ex.loadavg),
        "CPU pressure": _pressure(ex, "cpu"),
        "Context switches/s": "{:,.0f}".format(ex.ctx_switches_ps),
        "Interrupts/s": "{:,.0f}".format(ex.interrupts_ps),
        "Governor": ex.governor or "N/A",
        "Temperature": "{:.0f} °C".format(temp) if temp is not None else "N/A",
    }


def mem_values(ex):
    info = ex.meminfo
    huge_total = info.get("HugePages_Total", 0)
    return {
        "Memory pressure": _pressure(ex, "memory"),
        "Dirty": fmt_bytes(info.get("Dirty", 0)),
        "Writeback": fmt_bytes(info.get("Writeback", 0)),
        "Huge pages": "{}/{} free".format(info.get("HugePages_Free", 0), huge_total) if huge_total else "None",
        "Swappiness": ex.static.get("Swappiness", "N/A"),
        "Overcommit": ex.static.get("Overcommit", "N/A"),
    }


def disk_values(ex, disk):
    return {"I/O scheduler": ex.schedulers.get(disk, "N/A"), "I/O pressure": _pressure(ex, "io")}


def net_values(ex, name):
    nic = next((n for n in ex.nics if n[0] == name), None)
    if nic is None:
        return {k: "N/A" for k in NET_KEYS}
    return {"MAC address": nic[1] or "N/A", "MTU": str(nic[2]), "Duplex": nic[3] or "Unknown",
            "Errors (in/out)": "{:,} / {:,}".format(nic[4], nic[5]),
            "Drops (in/out)": "{:,} / {:,}".format(nic[6], nic[7])}


# -- the Tux tab -------------------------------------------------------------------------

def _rows(snap):
    """``[(section, [(key, value)])]`` describing everything Tux mode knows."""
    ex = snap.tux
    if ex is None:
        return [("Tux mode", [("Status", "Collecting data…")])]
    static = ex.static
    sections = []
    system = [(k, static[k]) for k in ("Kernel", "Kernel build", "Distribution", "Architecture", "Hostname",
                                      "Init system", "Desktop", "Display server", "cgroups") if k in static]
    system += [("Up time", fmt_uptime(snap.uptime)),
               ("Booted", datetime.datetime.fromtimestamp(snap.boot_time).strftime("%Y-%m-%d %H:%M:%S"))]
    sections.append(("System", system))

    sections.append(("Load", [
        ("Load average (1, 5, 15 min)", "{:.2f}  {:.2f}  {:.2f}".format(*ex.loadavg)),
        ("Runnable / total tasks", ex.running_tasks or "N/A"),
        ("Context switches/s", "{:,.0f}".format(ex.ctx_switches_ps)),
        ("Interrupts/s", "{:,.0f}".format(ex.interrupts_ps)),
        ("Soft interrupts/s", "{:,.0f}".format(ex.soft_interrupts_ps)),
        ("New processes/s", "{:,.1f}".format(ex.forks_ps)),
    ]))
    if ex.pressure:
        sections.append(("Pressure stall information (avg10 / avg60 / avg300)", [
            (key, "{:.2f}%  {:.2f}%  {:.2f}%".format(*values)) for key, values in sorted(ex.pressure.items())]))

    cpu = [("Governor", ex.governor or "N/A")]
    cpu += [("CPU {} frequency".format(i), "{:.0f} MHz".format(f)) for i, f in enumerate(ex.cpu_freqs)]
    sections.append(("CPU", cpu))
    vulns = static.get("vulnerabilities") or {}
    if vulns:
        sections.append(("CPU vulnerabilities", sorted(vulns.items())))

    info = ex.meminfo
    memory = [(label, fmt_bytes(info[key])) for label, key in (
        ("Dirty", "Dirty"), ("Writeback", "Writeback"), ("Active", "Active"), ("Inactive", "Inactive"),
        ("Anonymous pages", "AnonPages"), ("Mapped", "Mapped"), ("Shmem", "Shmem"), ("Slab", "Slab"),
        ("Page tables", "PageTables"), ("Mlocked", "Mlocked"), ("Unevictable", "Unevictable"),
        ("Swap cached", "SwapCached"), ("Zswap (compressed)", "Zswap"), ("Zswapped (original)", "Zswapped"))
        if key in info]
    if info.get("HugePages_Total"):
        memory.append(("Huge pages", "{} total, {} free, {} each".format(
            info["HugePages_Total"], info.get("HugePages_Free", 0), fmt_bytes(info.get("Hugepagesize", 0)))))
    memory += [("Swappiness", static.get("Swappiness", "N/A")), ("Overcommit", static.get("Overcommit", "N/A"))]
    sections.append(("Memory", memory))

    sensors = [("{} — {}".format(chip, label),
                "{:.1f} °C".format(cur) + ("  (high {:.0f}, critical {:.0f})".format(high, crit)
                                               if high and crit else ""))
               for chip, label, cur, high, crit in ex.temperatures]
    sensors += [("{} — {}".format(chip, label), "{} RPM".format(rpm)) for chip, label, rpm in ex.fans]
    if ex.battery is not None:
        bat = ex.battery
        state = "charging" if bat.power_plugged else "discharging"
        sensors.append(("Battery", "{:.0f}% ({})".format(bat.percent, state)))
    sections.append(("Sensors", sensors or [("Sensors", "No sensors reported")]))

    if ex.filesystems:
        sections.append(("Filesystems", [
            (mount, "{} {} — {} of {} used ({:.0f}%)".format(
                device, fstype, fmt_bytes(used), fmt_bytes(total), 100.0 * used / total if total else 0))
            for mount, device, fstype, used, total in ex.filesystems]))
    if ex.schedulers:
        sections.append(("Disk I/O schedulers", sorted(ex.schedulers.items())))
    if ex.nics:
        sections.append(("Network adapters", [
            (name, "MAC {}  MTU {}  {} duplex  errors {}/{}  drops {}/{}".format(mac or "-", mtu, duplex or "?",
                                                                               ei, eo, di, do))
            for name, mac, mtu, duplex, ei, eo, di, do in ex.nics]))
    used, limit = ex.file_handles
    sections.append(("Kernel limits", [
        ("Open file handles", "{:,} of {:,}".format(used, limit) if limit else "N/A"),
        ("PID max", static.get("PID max", "N/A")), ("Threads max", static.get("Threads max", "N/A")),
        ("inotify watches max", static.get("inotify watches max", "N/A")),
    ]))
    return sections


class TuxPanel(QtWidgets.QWidget):
    """The *Tux* tab: every Linux fact Windows has no place for."""

    def __init__(self, win8=False, parent=None):
        super().__init__(parent)
        self.setObjectName("win8page" if win8 else "")
        layout = QtWidgets.QVBoxLayout(self)
        margin = 0 if win8 else 6
        layout.setContentsMargins(margin, margin, margin, margin)
        self.tree = make_tree(["Property", "Value"], root_decorated=True)
        self.tree.setSortingEnabled(False)
        self.tree.header().resizeSection(0, 280)
        self.sync = ItemSync(self.tree)
        self.section_syncs = {}
        layout.addWidget(self.tree, 1)
        if win8:
            from ..win8.common import install_header
            install_header(self.tree)
            self.tree.setHeaderLabels(["Property", "Value"])
            self.tree.setSortingEnabled(False)
            self.tree.header().setFixedHeight(26)
            self.tree.header().resizeSection(0, 280)
        self._expanded = set()

    def update_snapshot(self, snap):
        with bulk_update(self.tree):
            self.sync.begin()
            for section, rows in _rows(snap):
                parent = self.sync.get(section)
                set_cell(parent, 0, section)
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                parent.setFirstColumnSpanned(True)
                if section not in self._expanded:
                    parent.setExpanded(True)
                    self._expanded.add(section)
                sync = self.section_syncs.setdefault(section, ItemSync(self.tree, parent))
                sync.begin()
                for key, value in rows:
                    item = sync.get(key)
                    set_cell(item, 0, str(key))
                    set_cell(item, 1, str(value))
                    item.setToolTip(1, str(value))
                sync.end()
            self.sync.end()
        for section in [s for s in self.section_syncs if s not in self.sync.items]:
            del self.section_syncs[section]


def tux_title(title):
    return title + " \u2014 Tux mode"


USER_COLUMNS = ["UID", "Groups", "Shell", "Home"]


def account_info(name):
    """``[uid, groups, shell, home]`` for the Users tab in Tux mode."""
    try:
        import grp
        import pwd
        pw = pwd.getpwnam(name)
    except (ImportError, KeyError):
        return ["", "", "", ""]
    try:
        groups = sorted(g.gr_name for g in grp.getgrall() if name in g.gr_mem or g.gr_gid == pw.pw_gid)
    except OSError:
        groups = []
    return [str(pw.pw_uid), ", ".join(groups), pw.pw_shell, pw.pw_dir]
