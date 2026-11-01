"""GPU monitoring (Windows 10 *GPU* columns and performance page).

Device totals come from sysfs (``gpu_busy_percent`` and ``mem_info_*`` on
amdgpu) or ``nvidia-smi``. Per-process usage comes from the kernel's DRM
client statistics in ``/proc/<pid>/fdinfo`` (Linux 5.19+, supported by amdgpu,
i915, xe, msm, panfrost, v3d and others). Like Windows, a process' GPU
utilization is the busiest engine it uses.
"""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

VENDORS = {"0x8086": "Intel", "0x1002": "AMD", "0x10de": "NVIDIA", "0x1af4": "Virtio", "0x15ad": "VMware",
           "0x1234": "QEMU", "0x5143": "Qualcomm"}

# DRM engine names mapped to the names Windows uses
ENGINE_NAMES = {
    "gfx": "3D", "render": "3D", "rcs": "3D", "3d": "3D",
    "compute": "Compute", "ccs": "Compute",
    "copy": "Copy", "bcs": "Copy", "sdma": "Copy", "dma": "Copy",
    "dec": "Video Decode", "video": "Video Decode", "vcs": "Video Decode", "jpeg": "Video Decode",
    "enc": "Video Encode", "enc_1": "Video Encode", "video-enhance": "Video Processing",
    "vecs": "Video Processing",
}


def engine_label(name):
    return ENGINE_NAMES.get(name, ENGINE_NAMES.get(re.sub(r"[_-]?\d+$", "", name), name.title()))


@dataclass
class GpuSample:
    index: int
    name: str = "GPU"
    vendor: str = ""
    driver: str = ""
    driver_version: str = ""
    location: str = ""
    pdev: str = ""
    utilization: float = 0.0
    engines: dict = field(default_factory=dict)  # Windows engine label -> percent
    dedicated_used: int = 0
    dedicated_total: int = 0
    shared_used: int = 0
    shared_total: int = 0

    @property
    def title(self):
        return "GPU {}".format(self.index)


@dataclass
class GpuDevice:
    index: int
    card: str
    path: str  # sysfs device directory
    pdev: str
    vendor: str
    name: str
    driver: str
    driver_version: str
    location: str


def _read(path, default=""):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return default


def _int(text, default=0):
    try:
        return int(text)
    except (TypeError, ValueError):
        return default


def pci_location(pdev):
    """``0000:03:00.0`` -> ``PCI bus 3, device 0, function 0`` (as Windows shows it)."""
    match = re.match(r"(?:[0-9a-f]+:)?([0-9a-f]+):([0-9a-f]+)\.([0-9a-f])$", pdev or "", re.I)
    if not match:
        return pdev or ""
    bus, dev, fn = (int(x, 16) for x in match.groups())
    return "PCI bus {}, device {}, function {}".format(bus, dev, fn)


def _lspci_name(pdev):
    if not pdev or not shutil.which("lspci"):
        return ""
    try:
        out = subprocess.run(["lspci", "-mm", "-s", pdev], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    parts = re.findall(r'"([^"]*)"', out)
    if len(parts) >= 3:
        vendor = parts[1].split(" [")[0].replace(" Corporation", "").replace(", Inc.", "")
        device = parts[2]
        if "[" in device and "]" in device:
            device = device[device.index("[") + 1:device.rindex("]")]
        return "{} {}".format(vendor, device)
    return ""


def find_devices(sys_root="/sys"):
    devices = []
    drm = os.path.join(sys_root, "class", "drm")
    try:
        cards = sorted((c for c in os.listdir(drm) if re.fullmatch(r"card\d+", c)), key=lambda c: int(c[4:]))
    except OSError:
        return devices
    for card in cards:
        path = os.path.realpath(os.path.join(drm, card, "device"))
        uevent = _read(os.path.join(path, "uevent"))
        pdev = ""
        match = re.search(r"^PCI_SLOT_NAME=(.+)$", uevent, re.M)
        if match:
            pdev = match.group(1).strip()
        driver_link = os.path.join(path, "driver")
        driver = os.path.basename(os.path.realpath(driver_link)) if os.path.exists(driver_link) else ""
        vendor = VENDORS.get(_read(os.path.join(path, "vendor")).lower(), "")
        name = _read(os.path.join(path, "product_name")) or _lspci_name(pdev) or \
            "{} GPU ({})".format(vendor or "Unknown", driver or card)
        version = _read(os.path.join(sys_root, "module", driver, "version")) if driver else ""
        devices.append(GpuDevice(len(devices), card, path, pdev, vendor, name, driver,
                                 version or os.uname().release, pci_location(pdev)))
    return devices


def parse_fdinfo(text):
    """Parse a DRM fdinfo file; returns ``None`` if it is not a DRM client."""
    info = {"engines": {}, "capacity": {}, "cycles": {}, "total_cycles": {}, "memory": {}}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if key == "drm-driver":
            info["driver"] = value
        elif key == "drm-pdev":
            info["pdev"] = value
        elif key == "drm-client-id":
            info["client"] = value
        elif key.startswith("drm-engine-capacity-"):
            info["capacity"][key[len("drm-engine-capacity-"):]] = _int(value, 1) or 1
        elif key.startswith("drm-engine-"):
            info["engines"][key[len("drm-engine-"):]] = _int(value.split()[0])
        elif key.startswith("drm-total-cycles-"):
            info["total_cycles"][key[len("drm-total-cycles-"):]] = _int(value.split()[0])
        elif key.startswith("drm-cycles-"):
            info["cycles"][key[len("drm-cycles-"):]] = _int(value.split()[0])
        elif key.startswith(("drm-memory-", "drm-resident-")):
            region = key.split("-", 2)[2]
            amount, _, unit = value.partition(" ")
            mult = {"": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3}.get(unit.strip(), 1)
            # prefer drm-resident-* when both old and new style keys are present
            if key.startswith("drm-resident-") or region not in info["memory"]:
                info["memory"][region] = _int(amount) * mult
    if "driver" not in info:
        return None
    return info


def _is_shared_region(region):
    return region in ("gtt", "system", "shared", "stolen-system", "cpu")


class GpuSampler:
    """Samples GPU devices and attributes usage to processes."""

    RESCAN_EVERY = 3  # full fd scans are the expensive part

    def __init__(self, sys_root="/sys", proc_root="/proc", nvidia=True):
        self.sys_root, self.proc_root = sys_root, proc_root
        self.devices = find_devices(sys_root)
        self.nvidia = bool(nvidia and shutil.which("nvidia-smi"))
        self._nv_fields = "index,name,driver_version,pci.bus_id,utilization.gpu,utilization.encoder," \
                          "utilization.decoder,memory.used,memory.total"
        self._prev = {}  # client key -> (ns engines, cycles, total_cycles)
        self._drm_fds = {}  # pid -> [fd]
        self._tick = 0

    @property
    def available(self):
        return bool(self.devices) or self.nvidia

    def _scan_fds(self, pids):
        found = {}
        for pid in pids:
            fd_dir = os.path.join(self.proc_root, str(pid), "fd")
            try:
                fds = os.listdir(fd_dir)
            except OSError:
                continue
            for fd in fds:
                try:
                    target = os.readlink(os.path.join(fd_dir, fd))
                except OSError:
                    continue
                if target.startswith("/dev/dri/"):
                    found.setdefault(pid, []).append(fd)
        return found

    def _clients(self, pids):
        if self._tick % self.RESCAN_EVERY == 0:
            self._drm_fds = self._scan_fds(pids)
        self._tick += 1
        clients = {}
        for pid, fds in self._drm_fds.items():
            for fd in fds:
                info = parse_fdinfo(_read(os.path.join(self.proc_root, str(pid), "fdinfo", fd)))
                if info is None:
                    continue
                key = (info.get("pdev", ""), info.get("driver", ""), info.get("client", "{}:{}".format(pid, fd)))
                if key not in clients:  # a client shared after fork() counts once
                    clients[key] = (pid, info)
        return clients

    def sample(self, procs, dt):
        """Fill ``proc.gpu*`` fields of ``procs`` (pid -> ProcInfo); return [GpuSample]."""
        gpus = [GpuSample(index=d.index, name=d.name, vendor=d.vendor, driver=d.driver,
                          driver_version=d.driver_version, location=d.location, pdev=d.pdev)
                for d in self.devices]
        by_pdev = {g.pdev: g for g in gpus}
        engine_sum = {}  # (gpu index, label) -> percent
        mem_sum = {}  # (gpu index, shared?) -> bytes
        current = {}
        if self.devices:
            for key, (pid, info) in self._clients(procs.keys()).items():
                gpu = by_pdev.get(info.get("pdev", "")) or (gpus[0] if len(gpus) == 1 else None)
                current[key] = (dict(info["engines"]), dict(info["cycles"]), dict(info["total_cycles"]))
                prev = self._prev.get(key)
                proc = procs.get(pid)
                if gpu is None or proc is None:
                    continue
                for region, amount in info["memory"].items():
                    shared = _is_shared_region(region)
                    if shared:
                        proc.gpu_shared += amount
                    else:
                        proc.gpu_dedicated += amount
                    mem_sum[(gpu.index, shared)] = mem_sum.get((gpu.index, shared), 0) + amount
                if prev is None or dt <= 0:
                    continue
                per_engine = {}
                for engine, value in info["engines"].items():
                    cap = info["capacity"].get(engine, 1)
                    used = max(0, value - prev[0].get(engine, value))
                    per_engine[engine] = 100.0 * used / (dt * 1e9 * cap)
                for engine, value in info["cycles"].items():
                    total = info["total_cycles"].get(engine, 0) - prev[2].get(engine, 0)
                    if total > 0:
                        cap = info["capacity"].get(engine, 1)
                        per_engine[engine] = 100.0 * max(0, value - prev[1].get(engine, value)) / (total * cap)
                for engine, pct in per_engine.items():
                    pct = min(100.0, pct)
                    label = engine_label(engine)
                    engine_sum[(gpu.index, label)] = engine_sum.get((gpu.index, label), 0.0) + pct
                    if pct > proc.gpu:
                        proc.gpu = pct
                        proc.gpu_engine = "GPU {} - {}".format(gpu.index, label)
        self._prev = current

        for gpu, dev in zip(gpus, self.devices):
            engines = {label: min(100.0, pct) for (idx, label), pct in engine_sum.items() if idx == gpu.index}
            for label in ("3D", "Copy", "Video Encode", "Video Decode"):
                engines.setdefault(label, 0.0)
            gpu.engines = engines
            busy = _read(os.path.join(dev.path, "gpu_busy_percent"))
            gpu.utilization = float(busy) if busy.isdigit() else max(engines.values(), default=0.0)
            if busy.isdigit():
                engines["3D"] = max(engines["3D"], float(busy))
            gpu.dedicated_used = _int(_read(os.path.join(dev.path, "mem_info_vram_used")))
            gpu.dedicated_total = _int(_read(os.path.join(dev.path, "mem_info_vram_total")))
            gpu.shared_used = _int(_read(os.path.join(dev.path, "mem_info_gtt_used")))
            gpu.shared_total = _int(_read(os.path.join(dev.path, "mem_info_gtt_total")))
            gpu.dedicated_used = gpu.dedicated_used or mem_sum.get((gpu.index, False), 0)
            gpu.shared_used = gpu.shared_used or mem_sum.get((gpu.index, True), 0)

        if self.nvidia:
            self._sample_nvidia(gpus)
        return gpus

    def _sample_nvidia(self, gpus):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=" + self._nv_fields, "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            return
        if out.returncode != 0 and "utilization.encoder" in self._nv_fields:
            # older drivers do not know the encoder/decoder fields
            self._nv_fields = "index,name,driver_version,pci.bus_id,utilization.gpu,memory.used,memory.total"
            return self._sample_nvidia(gpus)
        for sample in parse_nvidia_smi(out.stdout, self._nv_fields):
            pdev = sample.pdev.lower()
            existing = next((g for g in gpus if g.pdev and pdev.endswith(g.pdev.lower())), None)
            if existing is None:
                sample.index = len(gpus)
                gpus.append(sample)
            else:
                existing.name, existing.driver_version = sample.name, sample.driver_version
                existing.utilization, existing.engines = sample.utilization, sample.engines
                existing.dedicated_used, existing.dedicated_total = sample.dedicated_used, sample.dedicated_total


def parse_nvidia_smi(text, fields):
    names = fields.split(",")
    samples = []
    for line in text.strip().splitlines():
        values = dict(zip(names, (v.strip() for v in line.split(","))))
        if "name" not in values:
            continue

        def num(key):
            try:
                return float(values.get(key, "0"))
            except ValueError:
                return 0.0

        util = num("utilization.gpu")
        samples.append(GpuSample(
            index=int(num("index")), name=values["name"], vendor="NVIDIA", driver="nvidia",
            driver_version=values.get("driver_version", ""), pdev=values.get("pci.bus_id", ""),
            location=pci_location(values.get("pci.bus_id", "")[-12:].lower()),
            utilization=util,
            engines={"3D": util, "Copy": 0.0, "Video Encode": num("utilization.encoder"),
                     "Video Decode": num("utilization.decoder")},
            dedicated_used=int(num("memory.used") * 1024 * 1024),
            dedicated_total=int(num("memory.total") * 1024 * 1024),
        ))
    return samples
