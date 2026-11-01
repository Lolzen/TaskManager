import struct

import pytest

from taskmanager.backend import gpu, sysinfo
from taskmanager.backend.sampler import ProcInfo

from . import fakegpu


def test_parse_fdinfo_ns_and_cycles():
    info = gpu.parse_fdinfo("drm-driver:\ti915\ndrm-pdev:\t0000:00:02.0\ndrm-client-id:\t7\n"
                            "drm-engine-render:\t1000 ns\ndrm-engine-capacity-video:\t2\n"
                            "drm-cycles-rcs:\t50\ndrm-total-cycles-rcs:\t900\n"
                            "drm-memory-system:\t4 MiB\ndrm-resident-system:\t3 MiB\n")
    assert info["driver"] == "i915" and info["client"] == "7"
    assert info["engines"] == {"render": 1000}
    assert info["capacity"] == {"video": 2}
    assert info["cycles"] == {"rcs": 50} and info["total_cycles"] == {"rcs": 900}
    assert info["memory"]["system"] == 3 * 2 ** 20  # drm-resident-* wins
    assert gpu.parse_fdinfo("pos: 0\nflags: 0\n") is None


def test_engine_labels_and_location():
    assert gpu.engine_label("gfx") == "3D"
    assert gpu.engine_label("render") == "3D"
    assert gpu.engine_label("vcs") == "Video Decode"
    assert gpu.engine_label("enc_1") == "Video Encode"
    assert gpu.engine_label("weird") == "Weird"
    assert gpu.pci_location("0000:03:00.0") == "PCI bus 3, device 0, function 0"


def test_gpu_sampler_attributes_usage(tmp_path):
    sys_root, proc_root = fakegpu.build(str(tmp_path))
    sampler = gpu.GpuSampler(sys_root=sys_root, proc_root=proc_root, nvidia=False)
    assert [d.name for d in sampler.devices] == ["AMD Radeon RX 6600"]
    assert sampler.devices[0].location == "PCI bus 3, device 0, function 0"
    fakegpu.set_client(proc_root, 100, 5, client=1, gfx_ns=0)
    fakegpu.set_client(proc_root, 100, 6, client=1, gfx_ns=0)  # same client via a dup'ed fd
    fakegpu.set_client(proc_root, 200, 9, client=2, gfx_ns=0, video_ns=0)

    def procs():
        return {100: ProcInfo(pid=100), 200: ProcInfo(pid=200)}

    first = sampler.sample(procs(), 1.0)
    assert first[0].utilization == 42  # gpu_busy_percent
    fakegpu.set_client(proc_root, 100, 5, client=1, gfx_ns=250_000_000)
    fakegpu.set_client(proc_root, 100, 6, client=1, gfx_ns=250_000_000)
    fakegpu.set_client(proc_root, 200, 9, client=2, gfx_ns=0, video_ns=100_000_000)
    current = procs()
    gpus = sampler.sample(current, 1.0)
    assert current[100].gpu == pytest.approx(25.0)
    assert current[100].gpu_engine == "GPU 0 - 3D"
    assert current[200].gpu == pytest.approx(10.0)
    assert current[200].gpu_engine == "GPU 0 - Video Decode"
    assert current[100].gpu_dedicated == 1024 * 1024  # counted once despite two fds
    assert current[100].gpu_shared == 2048 * 1024
    g = gpus[0]
    assert g.engines["3D"] == pytest.approx(42)  # busy percent beats the 25% client sum
    assert g.engines["Video Decode"] == pytest.approx(10)
    assert g.dedicated_total == 8 * 2 ** 30 and g.dedicated_used == 512 * 2 ** 20


def test_gpu_without_busy_percent_uses_engines(tmp_path):
    sys_root, proc_root = fakegpu.build(str(tmp_path), amd=False)
    sampler = gpu.GpuSampler(sys_root=sys_root, proc_root=proc_root, nvidia=False)
    fakegpu.set_client(proc_root, 100, 5, client=1, gfx_ns=0)
    sampler.sample({100: ProcInfo(pid=100)}, 1.0)
    fakegpu.set_client(proc_root, 100, 5, client=1, gfx_ns=600_000_000)
    gpus = sampler.sample({100: ProcInfo(pid=100)}, 1.0)
    assert gpus[0].utilization == pytest.approx(60)
    assert gpus[0].dedicated_used == 1024 * 1024  # summed from clients


def test_parse_nvidia_smi():
    fields = "index,name,driver_version,pci.bus_id,utilization.gpu,utilization.encoder," \
             "utilization.decoder,memory.used,memory.total"
    text = "0, NVIDIA GeForce RTX 3060, 550.54, 00000000:01:00.0, 37, 5, 0, 1024, 12288\n"
    (sample,) = gpu.parse_nvidia_smi(text, fields)
    assert sample.name == "NVIDIA GeForce RTX 3060"
    assert sample.utilization == 37 and sample.engines["Video Encode"] == 5
    assert sample.dedicated_total == 12288 * 2 ** 20
    assert sample.location == "PCI bus 1, device 0, function 0"


def test_smbios_memory_device():
    raw = bytearray(0x28)
    raw[0], raw[1] = 17, 0x28
    struct.pack_into("<H", raw, 0x0C, 8192)  # 8 GB
    raw[0x0E] = 0x0D  # SODIMM
    struct.pack_into("<H", raw, 0x15, 3200)
    struct.pack_into("<H", raw, 0x20, 2933)  # configured speed wins
    assert sysinfo.parse_smbios_memory_device(bytes(raw)) == (8 * 2 ** 30, "SODIMM", 2933)
    empty = bytearray(raw)
    struct.pack_into("<H", empty, 0x0C, 0)
    assert sysinfo.parse_smbios_memory_device(bytes(empty))[0] == 0


def test_memory_hardware_from_memory_blocks(tmp_path):
    base = tmp_path / "devices" / "system" / "memory"
    base.mkdir(parents=True)
    (base / "block_size_bytes").write_text("8000000\n")
    for idx, online in enumerate("1101"):
        (base / "memory{}".format(idx)).mkdir()
        (base / "memory{}".format(idx) / "online").write_text(online)
    if sysinfo.IS_LINUX:
        assert sysinfo.memory_hardware(str(tmp_path)).installed == 3 * 0x8000000


def test_disk_type(tmp_path):
    for name, rot, removable in (("sda", "1", "0"), ("sdb", "0", "0"), ("sdc", "0", "1")):
        q = tmp_path / "block" / name / "queue"
        q.mkdir(parents=True)
        (q / "rotational").write_text(rot)
        (tmp_path / "block" / name / "removable").write_text(removable)
    assert sysinfo.disk_type("sda", str(tmp_path)) == "HDD"
    assert sysinfo.disk_type("sdb", str(tmp_path)) == "SSD"
    assert sysinfo.disk_type("sdc", str(tmp_path)) == "Removable"
    assert sysinfo.disk_type("nvme0n1", str(tmp_path)) == "SSD"


def test_compressed_memory(tmp_path):
    zram = tmp_path / "block" / "zram0"
    zram.mkdir(parents=True)
    (zram / "mm_stat").write_text("104857600 20971520 22000000 0 22000000 0 0 0 0\n")
    assert sysinfo.compressed_memory({"Zswapped": 1000}, str(tmp_path)) == 104857600 + 1000


def test_wireless_and_bios_parsers():
    text = ("Inter-| sta-|   Quality        |   Discarded packets\n"
            " face | tus | link level noise |  nwid  crypt   frag\n"
            " wlan0: 0000   54.  -56.  -256        0      0      0\n")
    assert sysinfo.parse_proc_wireless(text) == {"wlan0": (54.0, -56.0)}
    out = "Startup finished in 7.016s (firmware) + 3.1s (loader) + 2.1s (kernel) + 9s (userspace) = 21s\n"
    assert sysinfo.parse_systemd_analyze(out) == pytest.approx(7.016)
    assert sysinfo.parse_systemd_analyze("Startup finished in 850ms (firmware) + 1s (kernel)") == 0.85
    assert sysinfo.parse_systemd_analyze("Startup finished in 2.1s (kernel)") is None


def test_binary_architecture(tmp_path):
    elf = tmp_path / "prog"
    elf.write_bytes(b"\x7fELF\x02\x01\x01" + b"\0" * 9 + struct.pack("<HH", 2, 62))
    arm = tmp_path / "arm"
    arm.write_bytes(b"\x7fELF\x02\x01\x01" + b"\0" * 9 + struct.pack("<HH", 2, 183))
    script = tmp_path / "script"
    script.write_bytes(b"#!/bin/sh\necho hi\n")
    assert sysinfo.binary_architecture(str(elf)) == "x64"
    assert sysinfo.binary_architecture(str(arm)) == "ARM64"
    assert sysinfo.binary_architecture(str(script)) == "Script"
    assert sysinfo.binary_architecture(str(tmp_path / "missing")) == ""


def test_power_levels():
    from taskmanager.win8.processes import POWER_LEVELS, power_level, power_score
    assert POWER_LEVELS[power_level(power_score(0.1, 0, 0))] == "Very low"
    assert POWER_LEVELS[power_level(power_score(3, 0, 0))] == "Low"
    assert POWER_LEVELS[power_level(power_score(10, 0, 0))] == "Moderate"
    assert POWER_LEVELS[power_level(power_score(5, 40, 0))] == "High"
    assert POWER_LEVELS[power_level(power_score(90, 0, 0))] == "Very high"
