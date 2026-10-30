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


# -- Windows 10 additions ------------------------------------------------------

def disk_type(name, sys_root="/sys"):
    """``SSD``, ``HDD`` or ``Removable`` like the Windows 10 disk page."""
    base = os.path.join(sys_root, "block", name)
    if _read(os.path.join(base, "removable")).strip() == "1":
        return "Removable"
    if name.startswith("nvme"):
        return "SSD"
    rotational = _read(os.path.join(base, "queue", "rotational")).strip()
    if rotational == "0":
        return "SSD"
    if rotational == "1":
        return "HDD"
    return ""


FORM_FACTORS = {0x03: "SIMM", 0x09: "DIMM", 0x0B: "Row of chips", 0x0D: "SODIMM", 0x0F: "FB-DIMM",
                0x10: "Die", 0x11: "CAMM"}


def parse_smbios_memory_device(raw):
    """Parse an SMBIOS type 17 (*Memory Device*) structure.

    Returns ``(size_bytes, form_factor, speed_mts)``; size is 0 for an empty slot.
    """
    if len(raw) < 0x15 or raw[0] != 17:
        return 0, "", 0
    length = raw[1]
    size = int.from_bytes(raw[0x0C:0x0E], "little")
    if size == 0xFFFF:
        size_bytes = 0
    elif size == 0x7FFF and length >= 0x20:
        size_bytes = int.from_bytes(raw[0x1C:0x20], "little") * 1024 ** 2
    elif size & 0x8000:
        size_bytes = (size & 0x7FFF) * 1024
    else:
        size_bytes = size * 1024 ** 2
    form = FORM_FACTORS.get(raw[0x0E], "")
    speed = int.from_bytes(raw[0x15:0x17], "little") if length >= 0x17 else 0
    if length >= 0x22:
        configured = int.from_bytes(raw[0x20:0x22], "little")
        speed = configured or speed
    return size_bytes, form, speed


@dataclass
class MemoryHardware:
    installed: int = 0
    speed_mts: int = 0
    slots_used: int = 0
    slots_total: int = 0
    form_factor: str = ""


def memory_hardware(sys_root="/sys"):
    """Installed RAM and DIMM details (DIMM details need root on Linux)."""
    hw = MemoryHardware()
    if IS_LINUX:
        for path in sorted(glob.glob(os.path.join(sys_root, "firmware", "dmi", "entries", "17-*", "raw"))):
            try:
                with open(path, "rb") as fh:
                    size, form, speed = parse_smbios_memory_device(fh.read())
            except OSError:
                continue
            hw.slots_total += 1
            if size:
                hw.slots_used += 1
                hw.installed += size
                hw.form_factor = hw.form_factor or form
                hw.speed_mts = hw.speed_mts or speed
        if not hw.installed:
            block = _read(os.path.join(sys_root, "devices", "system", "memory", "block_size_bytes")).strip()
            try:
                block_size = int(block, 16)
            except ValueError:
                block_size = 0
            online = 0
            for state in glob.glob(os.path.join(sys_root, "devices", "system", "memory", "memory*", "online")):
                online += _read(state).strip() == "1"
            hw.installed = block_size * online
    elif IS_MAC:
        size = _sysctl("hw.memsize")
        hw.installed = int(size) if size.isdigit() else 0
    return hw


def compressed_memory(info=None, sys_root="/sys"):
    """Bytes of memory currently held compressed (zswap + zram), Windows' *Compressed*."""
    info = meminfo() if info is None else info
    total = info.get("Zswapped", 0)
    for stat in glob.glob(os.path.join(sys_root, "block", "zram*", "mm_stat")):
        fields = _read(stat).split()
        if fields and fields[0].isdigit():
            total += int(fields[0])
    return total


def parse_proc_wireless(text):
    """``/proc/net/wireless`` -> {iface: (quality, level_dbm)}."""
    result = {}
    for line in text.splitlines()[2:]:
        if ":" not in line:
            continue
        name, rest = line.split(":", 1)
        parts = rest.split()
        if len(parts) >= 3:
            try:
                result[name.strip()] = (float(parts[1].rstrip(".")), float(parts[2].rstrip(".")))
            except ValueError:
                continue
    return result


def wifi_ssid(name):
    for cmd in (["iwgetid", "-r", name], ["iw", "dev", name, "link"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode != 0:
            continue
        if cmd[0] == "iwgetid":
            return out.stdout.strip()
        match = re.search(r"^\s*SSID:\s*(.+)$", out.stdout, re.M)
        if match:
            return match.group(1).strip()
    return ""


def wifi_signal(name):
    """Signal as Windows-like 0..4 bars plus dBm, or ``None``."""
    info = parse_proc_wireless(_read("/proc/net/wireless")).get(name)
    if info is None:
        return None
    quality, level = info
    bars = max(0, min(4, int(round(quality / 70.0 * 4)))) if quality else 0
    return bars, level


def parse_systemd_analyze(text):
    """Seconds spent in firmware (Windows 10's *Last BIOS time*), or ``None``."""
    match = re.search(r"([\d.]+)(ms|s|min)\s+\(firmware\)", text)
    if not match:
        return None
    value = float(match.group(1))
    return value / 1000.0 if match.group(2) == "ms" else value * (60 if match.group(2) == "min" else 1)


def last_bios_time():
    if not IS_LINUX:
        return None
    try:
        out = subprocess.run(["systemd-analyze", "time"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_systemd_analyze(out.stdout)


ELF_MACHINES = {3: "x86", 62: "x64", 40: "ARM", 183: "ARM64", 243: "RISC-V", 8: "MIPS", 20: "PowerPC",
                21: "PowerPC64", 22: "S390", 2: "SPARC", 43: "SPARC64", 258: "LoongArch"}
MACHO_CPUS = {7: "x86", 0x01000007: "x64", 12: "ARM", 0x0100000C: "ARM64"}


def binary_architecture(path):
    """Architecture of an executable (Windows 10 Details tab *Architecture*)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(20)
    except OSError:
        return ""
    if head[:4] == b"\x7fELF" and len(head) >= 20:
        order = "little" if head[5] == 1 else "big"
        return ELF_MACHINES.get(int.from_bytes(head[18:20], order), "")
    magic = int.from_bytes(head[:4], "little")
    if magic in (0xFEEDFACE, 0xFEEDFACF) and len(head) >= 8:
        return MACHO_CPUS.get(int.from_bytes(head[4:8], "little"), "")
    if head[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        return "Universal"
    if head[:2] == b"#!":
        return "Script"
    return ""
