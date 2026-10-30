"""Human readable formatting helpers shared by both layouts."""

KB = 1024
MB = KB * 1024
GB = MB * 1024


def fmt_kb(nbytes):
    """Windows 7 style memory value: ``12,345 K``."""
    return "{:,} K".format(int(nbytes // KB))


def fmt_mem_mb(nbytes):
    """Windows 8 style memory value: ``123.4 MB``."""
    return "{:,.1f} MB".format(nbytes / MB)


def fmt_bytes(nbytes, digits=1):
    """Scale a byte count to the largest sensible unit."""
    value = float(nbytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024 or unit == "TB":
            if unit == "B":
                return "{:.0f} B".format(value)
            return "{:.{d}f} {}".format(value, unit, d=digits)
        value /= 1024
    return "{:.{d}f} TB".format(value, d=digits)  # pragma: no cover


def fmt_gb(nbytes, digits=1):
    return "{:.{d}f} GB".format(nbytes / GB, d=digits)


def fmt_disk_rate(bps):
    """Per-process disk column: ``0.1 MB/s``."""
    return "{:.1f} MB/s".format(bps / MB)


def fmt_rate(bps):
    """Disk transfer rates in the performance tab: ``12.3 KB/s``."""
    return fmt_bytes(bps) + "/s"


def fmt_bits(bps):
    """Network throughput: ``8.0 Kbps``. ``bps`` is in *bytes* per second."""
    bits = bps * 8.0
    for unit in ("bps", "Kbps", "Mbps", "Gbps"):
        if bits < 1000 or unit == "Gbps":
            if unit == "bps":
                return "{:.0f} {}".format(bits, unit)
            return "{:.1f} {}".format(bits, unit)
        bits /= 1000.0
    return "{:.1f} Gbps".format(bits)  # pragma: no cover


def fmt_mbps(bps):
    """Per-process network column: ``0.1 Mbps``."""
    return "{:.1f} Mbps".format(bps * 8 / 1e6)


def fmt_link_speed(mbps):
    if not mbps:
        return "Unknown"
    if mbps >= 1000:
        return "{:g} Gbps".format(mbps / 1000.0)
    return "{:g} Mbps".format(mbps)


def fmt_uptime(seconds):
    """``D:HH:MM:SS`` like both Task Managers."""
    seconds = int(max(0, seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    return "{}:{:02d}:{:02d}:{:02d}".format(days, hours, minutes, secs)


def fmt_cpu_time(seconds):
    """Win7 *CPU Time* column: ``H:MM:SS``."""
    seconds = int(max(0, seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return "{}:{:02d}:{:02d}".format(hours, minutes, secs)


def fmt_pct(value):
    return "{:.0f}%".format(value)


def fmt_freq(mhz):
    if not mhz:
        return "Unknown"
    return "{:.2f} GHz".format(mhz / 1000.0)


def fmt_cache(nbytes):
    if not nbytes:
        return "N/A"
    if nbytes >= MB:
        return "{:g} MB".format(round(nbytes / MB, 1))
    return "{:g} KB".format(round(nbytes / KB, 1))
