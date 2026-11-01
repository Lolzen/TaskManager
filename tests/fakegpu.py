"""Builds fake sysfs/procfs trees with a DRM GPU and GPU-using processes."""

import os


def build(root, pdev="0000:03:00.0", amd=True):
    sys_root = os.path.join(root, "sys")
    proc_root = os.path.join(root, "proc")
    dev = os.path.join(sys_root, "devices", "pci0000:00", pdev)
    os.makedirs(os.path.join(dev, "drv"), exist_ok=True)
    os.makedirs(os.path.join(sys_root, "class", "drm", "card0"), exist_ok=True)
    os.makedirs(os.path.join(sys_root, "class", "drm", "card0-DP-1"), exist_ok=True)
    os.symlink(dev, os.path.join(sys_root, "class", "drm", "card0", "device"))
    os.symlink(os.path.join(sys_root, "bus", "pci", "drivers", "amdgpu"), os.path.join(dev, "driver"))
    os.makedirs(os.path.join(sys_root, "bus", "pci", "drivers", "amdgpu"), exist_ok=True)
    files = {
        "uevent": "DRIVER=amdgpu\nPCI_SLOT_NAME={}\n".format(pdev),
        "vendor": "0x1002",
        "product_name": "AMD Radeon RX 6600",
    }
    if amd:
        files.update({"gpu_busy_percent": "42", "mem_info_vram_used": str(512 * 2 ** 20),
                      "mem_info_vram_total": str(8 * 2 ** 30), "mem_info_gtt_used": str(64 * 2 ** 20),
                      "mem_info_gtt_total": str(4 * 2 ** 30)})
    for name, text in files.items():
        with open(os.path.join(dev, name), "w") as fh:
            fh.write(text)
    os.makedirs(proc_root, exist_ok=True)
    return sys_root, proc_root


def set_client(proc_root, pid, fd, client, gfx_ns, video_ns=0, vram_kib=1024, pdev="0000:03:00.0"):
    fd_dir = os.path.join(proc_root, str(pid), "fd")
    info_dir = os.path.join(proc_root, str(pid), "fdinfo")
    os.makedirs(fd_dir, exist_ok=True)
    os.makedirs(info_dir, exist_ok=True)
    link = os.path.join(fd_dir, str(fd))
    if not os.path.islink(link):
        os.symlink("/dev/dri/renderD128", link)
    with open(os.path.join(info_dir, str(fd)), "w") as fh:
        fh.write("pos:\t0\nflags:\t02100002\ndrm-driver:\tamdgpu\ndrm-pdev:\t{}\ndrm-client-id:\t{}\n"
                 "drm-memory-vram:\t{} KiB\ndrm-memory-gtt:\t2048 KiB\n"
                 "drm-engine-gfx:\t{} ns\ndrm-engine-dec:\t{} ns\n".format(pdev, client, vram_kib, gfx_ns, video_ns))
