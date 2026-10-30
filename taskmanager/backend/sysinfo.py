"""Static and slow-changing system information gathered from the OS.

Everything here degrades gracefully: on systems without ``/proc`` or ``/sys``
(macOS, the BSDs) values fall back to ``sysctl`` or are reported as unknown.
"""

import glob
import os
import platform
import re
import socket
import subprocess
import sys
from dataclasses import dataclass, field

import psutil

IS_LINUX = sys.platform.startswith("linux")
IS_MAC = sys.platform == "darwin"


def _read(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return default


def _sysctl(name):
    try:
        out = subprocess.run(
            ["sysctl", "-n", name], capture_output=True, text=True, timeout=2
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


@dataclass
class CpuInfo:
    model: str = "Unknown processor"
    sockets: int = 1
    cores: int = 1
    logical: int = 1
    base_mhz: float = 0.0
    max_mhz: float = 0.0
    virtualization: str = "Unknown"
    caches: dict = field(default_factory=dict)  # level ("L1", ...) -> bytes


def parse_size(text):
    """Parse sizes like ``32K``, ``1024 KB`` or ``8M`` into bytes."""
    match = re.match(r"\s*([\d.]+)\s*([KMG]?)", text or "", re.I)
    if not match:
        return 0
    mult = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}[match.group(2).upper()]
    return int(float(match.group(1)) * mult)


def linux_cache_sizes(root="/sys/devices/system/cpu"):
    """Total cache per level, counting every physical cache instance once."""
    seen = set()
    totals = {}
    for index in glob.glob(os.path.join(root, "cpu[0-9]*", "cache", "index[0-9]*")):
        level = _read(os.path.join(index, "level")).strip()
        ctype = _read(os.path.join(index, "type")).strip()
        shared = _read(os.path.join(index, "shared_cpu_list")).strip()
        size = parse_size(_read(os.path.join(index, "size")))
        if not level or not size:
            continue
        key = (level, ctype, shared)
        if key in seen:
            continue
        seen.add(key)
        name = "L" + level
        totals[name] = totals.get(name, 0) + size
    return totals


def get_cpu_info():
    info = CpuInfo()
    info.logical = psutil.cpu_count(logical=True) or 1
    info.cores = psutil.cpu_count(logical=False) or info.logical
    try:
        freq = psutil.cpu_freq()
    except (NotImplementedError, OSError, AttributeError):
        freq = None
    if freq:
        info.base_mhz = freq.current or 0.0
        info.max_mhz = freq.max or freq.current or 0.0

    if IS_LINUX:
        cpuinfo = _read("/proc/cpuinfo")
        model = re.search(r"^(model name|Model|Hardware)\s*:\s*(.+)$", cpuinfo, re.M)
        if model:
            info.model = model.group(2).strip()
        sockets = set(re.findall(r"^physical id\s*:\s*(\d+)", cpuinfo, re.M))
        info.sockets = max(1, len(sockets))
        flags = re.search(r"^(flags|Features)\s*:\s*(.+)$", cpuinfo, re.M)
        if flags:
            words = flags.group(2).split()
            if "vmx" in words or "svm" in words:
                info.virtualization = "Enabled"
            elif "hypervisor" in words:
                info.virtualization = "Virtual machine"
            else:
                info.virtualization = "Not available"
        info.caches = linux_cache_sizes()
    elif IS_MAC:
        info.model = _sysctl("machdep.cpu.brand_string") or platform.processor() or info.model
        info.sockets = int(_sysctl("hw.packages") or 1)
        for level, key in (("L1", "hw.l1dcachesize"), ("L2", "hw.l2cachesize"), ("L3", "hw.l3cachesize")):
            size = _sysctl(key)
            if size.isdigit() and int(size):
                info.caches[level] = int(size)
    else:
        info.model = _sysctl("hw.model") or platform.processor() or info.model
    return info


def parse_meminfo(text):
    """Parse ``/proc/meminfo`` into a dict of bytes."""
    values = {}
    for line in text.splitlines():
        match = re.match(r"([\w()]+):\s+(\d+)(?:\s+kB)?", line)
        if match:
            key, num = match.groups()
            values[key] = int(num) * (1024 if line.rstrip().endswith("kB") else 1)
    return values


def meminfo():
    if not IS_LINUX:
        return {}
    return parse_meminfo(_read("/proc/meminfo"))


def open_handles():
    """System wide number of allocated file handles (Windows' *Handles*)."""
    if IS_LINUX:
        parts = _read("/proc/sys/fs/file-nr").split()
        if parts and parts[0].isdigit():
            return int(parts[0])
    elif IS_MAC:
        value = _sysctl("kern.num_files")
        if value.isdigit():
            return int(value)
    return None


def nic_kind(name):
    if IS_LINUX and os.path.isdir("/sys/class/net/{}/wireless".format(name)):
        return "Wi-Fi"
    if name.startswith(("wl", "wlan", "wifi", "ath")):
        return "Wi-Fi"
    return "Ethernet"


def nic_addresses(name, addrs):
    ipv4 = ipv6 = ""
    for addr in addrs.get(name, []):
        if addr.family == socket.AF_INET and not ipv4:
            ipv4 = addr.address
        elif addr.family == socket.AF_INET6 and not ipv6:
            ipv6 = addr.address.split("%")[0]
    return ipv4, ipv6


def is_virtual_nic(name):
    if name == "lo" or name.startswith(("lo0", "lo")):
        return True
    return False


def whole_disks(names):
    """Filter ``disk_io_counters(perdisk=True)`` names down to whole devices."""
    result = []
    for name in names:
        if name.startswith(("loop", "ram", "fd", "sr")):
            continue
        if IS_LINUX:
            if os.path.isdir("/sys/block/" + name):
                result.append(name)
        elif IS_MAC:
            if re.fullmatch(r"disk\d+", name):
                result.append(name)
        else:
            result.append(name)
    return sorted(result) if result else sorted(n for n in names if not n.startswith("loop"))


def disk_capacity(name):
    if IS_LINUX:
        sectors = _read("/sys/block/{}/size".format(name)).strip()
        if sectors.isdigit():
            return int(sectors) * 512
    return 0


def disk_model(name):
    if IS_LINUX:
        model = _read("/sys/block/{}/device/model".format(name)).strip()
        if model:
            return model
    return ""


def swap_devices():
    if not IS_LINUX:
        return []
    lines = _read("/proc/swaps").splitlines()[1:]
    return [line.split()[0] for line in lines if line.split()]


def os_name():
    if IS_LINUX:
        release = _read("/etc/os-release")
        match = re.search(r'^PRETTY_NAME="?([^"\n]+)"?', release, re.M)
        if match:
            return match.group(1)
    if IS_MAC:
        return "macOS " + platform.mac_ver()[0]
    return "{} {}".format(platform.system(), platform.release())
