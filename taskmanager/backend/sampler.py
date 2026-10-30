"""Periodic sampling of processes and system counters.

``Sampler.sample()`` is pure Python and can be unit-tested without Qt. Rates
(CPU %, disk and network throughput) are derived from the difference between
two consecutive samples, which is exactly how Task Manager computes them.
"""

import os
import time
from dataclasses import dataclass, field

import psutil

from . import sysinfo
from .apps import AppRegistry

KIND_APP = "app"
KIND_BACKGROUND = "background"
KIND_SYSTEM = "system"

STATUS_LABELS = {
    psutil.STATUS_RUNNING: "Running",
    psutil.STATUS_SLEEPING: "Running",
    psutil.STATUS_DISK_SLEEP: "Running",
    psutil.STATUS_IDLE: "Running",
    psutil.STATUS_STOPPED: "Suspended",
    psutil.STATUS_TRACING_STOP: "Suspended",
    psutil.STATUS_ZOMBIE: "Zombie",
    psutil.STATUS_DEAD: "Terminated",
}

_ATTRS = [
    "pid", "ppid", "name", "exe", "cmdline", "username", "status", "cpu_times",
    "memory_info", "num_threads", "nice", "create_time", "uids", "terminal",
]
if hasattr(psutil.Process, "io_counters"):
    _ATTRS.append("io_counters")

SYSTEM_UID_MAX = 499 if sysinfo.IS_MAC else 999
ASSUMED_LINK_MBPS = 1000


@dataclass
class ProcInfo:
    pid: int
    ppid: int = 0
    name: str = ""
    exe: str = ""
    cmdline: str = ""
    username: str = ""
    uid: int = -1
    status: str = "Running"
    cpu: float = 0.0  # percent of the whole machine
    cpu_time: float = 0.0  # seconds
    mem_private: int = 0  # bytes, private working set equivalent
    mem_rss: int = 0
    disk_bps: float = 0.0
    io_read: int = 0
    io_write: int = 0
    threads: int = 0
    nice: int = 0
    create_time: float = 0.0
    terminal: str = ""
    kind: str = KIND_BACKGROUND
    app_id: str = ""
    app_name: str = ""
    description: str = ""
    icon: str = ""

    @property
    def display_name(self):
        return self.app_name or self.name


@dataclass
class CpuSample:
    total: float = 0.0
    kernel: float = 0.0
    per_cpu: list = field(default_factory=list)
    per_cpu_kernel: list = field(default_factory=list)
    freq_mhz: float = 0.0


@dataclass
class MemSample:
    total: int = 0
    available: int = 0
    used: int = 0
    free: int = 0
    cached: int = 0
    buffers: int = 0
    shared: int = 0
    modified: int = 0
    slab: int = 0
    kernel_stack: int = 0
    page_tables: int = 0
    commit: int = 0
    commit_limit: int = 0
    swap_total: int = 0
    swap_used: int = 0

    @property
    def percent(self):
        return 100.0 * self.used / self.total if self.total else 0.0


@dataclass
class DiskSample:
    name: str
    model: str = ""
    active: float = 0.0
    read_bps: float = 0.0
    write_bps: float = 0.0
    response_ms: float = 0.0
    capacity: int = 0
    formatted: int = 0
    mountpoints: list = field(default_factory=list)
    system_disk: bool = False
    page_file: bool = False

    @property
    def label(self):
        if self.mountpoints:
            return "{} ({})".format(self.name, " ".join(self.mountpoints[:2]))
        return self.name


@dataclass
class NetSample:
    name: str
    kind: str = "Ethernet"
    sent_bps: float = 0.0
    recv_bps: float = 0.0
    speed_mbps: int = 0
    is_up: bool = False
    ipv4: str = ""
    ipv6: str = ""

    @property
    def utilization(self):
        # Virtual adapters often report no link speed; measure them against 1 Gbps.
        speed = self.speed_mbps or ASSUMED_LINK_MBPS
        return min(100.0, 100.0 * (self.sent_bps + self.recv_bps) * 8 / (speed * 1e6))


@dataclass
class Snapshot:
    timestamp: float = 0.0
    interval: float = 1.0
    procs: dict = field(default_factory=dict)
    cpu: CpuSample = field(default_factory=CpuSample)
    mem: MemSample = field(default_factory=MemSample)
    disks: list = field(default_factory=list)
    nets: list = field(default_factory=list)
    boot_time: float = 0.0
    threads: int = 0
    handles: object = None
    users: list = field(default_factory=list)
    disk_total_bps: float = 0.0
    net_total_bps: float = 0.0

    @property
    def uptime(self):
        return self.timestamp - self.boot_time

    @property
    def process_count(self):
        return len(self.procs)


def classify(proc, own_uid, app):
    """Decide which Windows 8 group a process belongs to."""
    if sysinfo.IS_LINUX and (proc.pid == 2 or proc.ppid == 2 or (not proc.exe and not proc.cmdline)):
        return KIND_SYSTEM  # kernel thread
    if app is not None and proc.uid == own_uid:
        return KIND_APP
    if proc.uid == 0 or (0 <= proc.uid <= SYSTEM_UID_MAX and proc.uid != own_uid):
        return KIND_SYSTEM
    return KIND_BACKGROUND


def _short_cmdline(cmdline, limit=120):
    text = " ".join(cmdline or [])
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Sampler:
    def __init__(self, registry=None):
        self.registry = registry if registry is not None else AppRegistry()
        self.own_uid = os.getuid() if hasattr(os, "getuid") else -1
        self._prev_time = None
        self._prev_proc = {}  # (pid, create_time) -> (cpu_time, io_total)
        self._prev_cpu_times = None
        self._prev_percpu = None
        self._prev_disk = {}
        self._prev_net = {}
        self._app_cache = {}  # (name, exe) -> lookup result
        self._disk_static = {}
        self.boot_time = psutil.boot_time()
        self.ncpu = psutil.cpu_count() or 1

    # -- helpers ---------------------------------------------------------
    def _lookup_app(self, name, exe, cmd0):
        key = (name, exe, cmd0)
        if key not in self._app_cache:
            self._app_cache[key] = self.registry.lookup(name, exe, cmd0)
        return self._app_cache[key]

    @staticmethod
    def _busy(times):
        idle = getattr(times, "idle", 0.0) + getattr(times, "iowait", 0.0)
        total = sum(times)
        return total - idle, total, getattr(times, "system", 0.0) + getattr(times, "irq", 0.0) + getattr(times, "softirq", 0.0)

    def _cpu_percent(self, prev, cur):
        if prev is None:
            return 0.0, 0.0
        busy0, total0, kern0 = self._busy(prev)
        busy1, total1, kern1 = self._busy(cur)
        span = total1 - total0
        if span <= 0:
            return 0.0, 0.0
        return (max(0.0, min(100.0, 100.0 * (busy1 - busy0) / span)),
                max(0.0, min(100.0, 100.0 * (kern1 - kern0) / span)))

    # -- sampling --------------------------------------------------------
    def sample(self):
        now = time.time()
        dt = (now - self._prev_time) if self._prev_time else 0.0
        snap = Snapshot(timestamp=now, interval=dt, boot_time=self.boot_time)

        self._sample_cpu(snap)
        self._sample_mem(snap)
        self._sample_procs(snap, dt)
        self._sample_disks(snap, dt)
        self._sample_nets(snap, dt)
        snap.handles = sysinfo.open_handles()
        try:
            snap.users = psutil.users()
        except (OSError, RuntimeError):
            snap.users = []

        self._prev_time = now
        return snap

    def _sample_cpu(self, snap):
        cur = psutil.cpu_times()
        percpu = psutil.cpu_times(percpu=True)
        snap.cpu.total, snap.cpu.kernel = self._cpu_percent(self._prev_cpu_times, cur)
        prev = self._prev_percpu or [None] * len(percpu)
        for p, c in zip(prev, percpu):
            total, kernel = self._cpu_percent(p, c)
            snap.cpu.per_cpu.append(total)
            snap.cpu.per_cpu_kernel.append(kernel)
        self._prev_cpu_times, self._prev_percpu = cur, percpu
        try:
            freq = psutil.cpu_freq()
            snap.cpu.freq_mhz = freq.current if freq else 0.0
        except (NotImplementedError, OSError, AttributeError):
            snap.cpu.freq_mhz = 0.0

    def _sample_mem(self, snap):
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        m = snap.mem
        m.total, m.available, m.free = vm.total, vm.available, vm.free
        m.used = vm.total - vm.available
        m.cached = getattr(vm, "cached", 0) + getattr(vm, "buffers", 0)
        m.buffers = getattr(vm, "buffers", 0)
        m.shared = getattr(vm, "shared", 0)
        m.swap_total, m.swap_used = sw.total, sw.used
        info = sysinfo.meminfo()
        if info:
            m.modified = info.get("Dirty", 0) + info.get("Writeback", 0)
            m.slab = info.get("Slab", 0)
            m.kernel_stack = info.get("KernelStack", 0)
            m.page_tables = info.get("PageTables", 0)
            m.commit = info.get("Committed_AS", m.used)
            m.commit_limit = info.get("CommitLimit", m.total + m.swap_total)
        else:
            m.commit = m.used + m.swap_used
            m.commit_limit = m.total + m.swap_total

    def _sample_procs(self, snap, dt):
        seen = {}
        threads = 0
        scale = 100.0 / (dt * self.ncpu) if dt > 0 else 0.0
        for p in psutil.process_iter(_ATTRS, ad_value=None):
            info = p.info
            pid = info["pid"]
            cmdline = info.get("cmdline") or []
            exe = info.get("exe") or ""
            name = info.get("name") or (os.path.basename(cmdline[0]) if cmdline else str(pid))
            ctimes = info.get("cpu_times")
            cpu_time = (ctimes.user + ctimes.system) if ctimes else 0.0
            mem = info.get("memory_info")
            rss = mem.rss if mem else 0
            private = rss - getattr(mem, "shared", 0) if mem else 0
            io = info.get("io_counters")
            io_read = getattr(io, "read_bytes", 0) if io else 0
            io_write = getattr(io, "write_bytes", 0) if io else 0
            uids = info.get("uids")
            proc = ProcInfo(
                pid=pid,
                ppid=info.get("ppid") or 0,
                name=name,
                exe=exe,
                cmdline=_short_cmdline(cmdline, 4096),
                username=info.get("username") or (str(uids.real) if uids else ""),
                uid=uids.real if uids else -1,
                status=STATUS_LABELS.get(info.get("status"), "Running"),
                cpu_time=cpu_time,
                mem_private=max(0, private),
                mem_rss=rss,
                io_read=io_read,
                io_write=io_write,
                threads=info.get("num_threads") or 0,
                nice=info.get("nice") or 0,
                create_time=info.get("create_time") or 0.0,
                terminal=info.get("terminal") or "",
            )
            key = (pid, proc.create_time)
            prev = self._prev_proc.get(key)
            if prev is not None and dt > 0:
                proc.cpu = max(0.0, min(100.0, (cpu_time - prev[0]) * scale))
                proc.disk_bps = max(0.0, (io_read + io_write - prev[1]) / dt)
            seen[key] = (cpu_time, io_read + io_write)

            app = self._lookup_app(name, exe, cmdline[0] if cmdline else "")
            proc.kind = classify(proc, self.own_uid, app)
            if app is not None and proc.kind == KIND_APP:
                proc.app_id, proc.app_name, proc.description, proc.icon = app
            elif app is not None:
                proc.description = app[2]
            else:
                proc.description = _short_cmdline(cmdline) or name
            threads += proc.threads
            snap.procs[pid] = proc
        self._prev_proc = seen
        snap.threads = threads

    def _disk_meta(self, name):
        if name not in self._disk_static:
            mounts, formatted = [], 0
            try:
                parts = psutil.disk_partitions(all=False)
            except OSError:
                parts = []
            for part in parts:
                dev = os.path.basename(part.device)
                if dev == name or (dev.startswith(name) and dev[len(name):].lstrip("p").isdigit()) \
                        or (sysinfo.IS_MAC and dev.startswith(name + "s")):
                    mounts.append(part.mountpoint)
                    try:
                        formatted += psutil.disk_usage(part.mountpoint).total
                    except OSError:
                        pass
            swaps = [os.path.basename(s) for s in sysinfo.swap_devices()]
            page = any(s == name or (s.startswith(name) and s[len(name):].lstrip("p").isdigit()) for s in swaps)
            self._disk_static[name] = (sorted(mounts, key=len), formatted, page)
        return self._disk_static[name]

    def _sample_disks(self, snap, dt):
        try:
            counters = psutil.disk_io_counters(perdisk=True) or {}
        except (OSError, RuntimeError):
            counters = {}
        total = 0.0
        for name in sysinfo.whole_disks(counters.keys()):
            cur = counters[name]
            d = DiskSample(name=name, model=sysinfo.disk_model(name), capacity=sysinfo.disk_capacity(name))
            d.mountpoints, d.formatted, d.page_file = self._disk_meta(name)
            d.system_disk = "/" in d.mountpoints
            prev = self._prev_disk.get(name)
            if prev is not None and dt > 0:
                d.read_bps = max(0, cur.read_bytes - prev.read_bytes) / dt
                d.write_bps = max(0, cur.write_bytes - prev.write_bytes) / dt
                busy = getattr(cur, "busy_time", None)
                if busy is not None:
                    d.active = max(0.0, min(100.0, (busy - prev.busy_time) / (dt * 10.0)))
                elif d.read_bps or d.write_bps:
                    d.active = min(100.0, (cur.read_time + cur.write_time - prev.read_time - prev.write_time) / (dt * 10.0))
                ops = (cur.read_count + cur.write_count) - (prev.read_count + prev.write_count)
                if ops > 0:
                    d.response_ms = ((cur.read_time + cur.write_time) - (prev.read_time + prev.write_time)) / ops
            total += d.read_bps + d.write_bps
            snap.disks.append(d)
        self._prev_disk = counters
        snap.disk_total_bps = total

    def _sample_nets(self, snap, dt):
        try:
            counters = psutil.net_io_counters(pernic=True) or {}
            stats = psutil.net_if_stats()
            addrs = psutil.net_if_addrs()
        except (OSError, RuntimeError):
            counters, stats, addrs = {}, {}, {}
        total = 0.0
        for name in sorted(counters):
            if sysinfo.is_virtual_nic(name):
                continue
            cur = counters[name]
            st = stats.get(name)
            n = NetSample(name=name, kind=sysinfo.nic_kind(name))
            if st is not None:
                n.speed_mbps, n.is_up = st.speed, st.isup
            n.ipv4, n.ipv6 = sysinfo.nic_addresses(name, addrs)
            prev = self._prev_net.get(name)
            if prev is not None and dt > 0:
                n.sent_bps = max(0, cur.bytes_sent - prev.bytes_sent) / dt
                n.recv_bps = max(0, cur.bytes_recv - prev.bytes_recv) / dt
            total += n.sent_bps + n.recv_bps
            snap.nets.append(n)
        self._prev_net = counters
        snap.net_total_bps = total
