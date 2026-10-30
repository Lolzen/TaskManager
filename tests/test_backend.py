import json
import os
import time

import pytest

from taskmanager.backend import apps, formatting, history, services, startup, sysinfo
from taskmanager.backend.sampler import (KIND_APP, KIND_BACKGROUND, KIND_SYSTEM, NetSample, ProcInfo,
                                         Sampler, Snapshot, classify)


# -- formatting -----------------------------------------------------------------

def test_formatting():
    assert formatting.fmt_kb(12_345 * 1024) == "12,345 K"
    assert formatting.fmt_mem_mb(1536 * 1024) == "1.5 MB"
    assert formatting.fmt_uptime(90061) == "1:01:01:01"
    assert formatting.fmt_cpu_time(3725) == "1:02:05"
    assert formatting.fmt_bits(1000) == "8.0 Kbps"
    assert formatting.fmt_bits(10) == "80 bps"
    assert formatting.fmt_bytes(2048) == "2.0 KB"
    assert formatting.fmt_link_speed(1000) == "1 Gbps"
    assert formatting.fmt_link_speed(0) == "Unknown"
    assert formatting.fmt_cache(256 * 1024) == "256 KB"


# -- desktop entries / app detection --------------------------------------------

@pytest.mark.parametrize("line,expected", [
    ("firefox %u", "firefox"),
    ("/usr/bin/gedit --new-window %U", "gedit"),
    ("env GDK_BACKEND=x11 /opt/app/bin/thing", "thing"),
    ("FOO=1 code --unity-launch %F", "code"),
    ("/usr/bin/flatpak run --branch=stable --command=foo org.gnome.Calculator", "calculator"),
    ("", ""),
])
def test_exec_program(line, expected):
    assert apps.exec_program(line) == expected


def test_registry_lookup(tmp_path):
    (tmp_path / "org.example.Editor.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Editor\nGenericName=Text Editor\n"
        "Exec=/usr/bin/example-editor %F\nIcon=accessories-text-editor\n")
    (tmp_path / "hidden.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Hidden\nExec=hidden\nNoDisplay=true\n")
    reg = apps.AppRegistry([str(tmp_path)])
    assert reg.lookup("example-editor", "/usr/bin/example-editor", "")[1] == "Editor"
    assert reg.lookup("x", "", "/usr/bin/example-editor")[2] == "Text Editor"
    assert reg.lookup("hidden", "/usr/bin/hidden", "") is None
    bundle = reg.lookup("Safari", "/Applications/Safari.app/Contents/MacOS/Safari", "")
    assert bundle[1] == "Safari"


def test_classify():
    kernel = ProcInfo(pid=10, ppid=2, name="kworker/0:1")
    daemon = ProcInfo(pid=11, ppid=1, name="sshd", exe="/usr/sbin/sshd", cmdline="sshd", uid=0)
    mine = ProcInfo(pid=12, ppid=1, name="bash", exe="/bin/bash", cmdline="bash", uid=1000)
    other = ProcInfo(pid=13, ppid=1, name="bash", exe="/bin/bash", cmdline="bash", uid=1001)
    app = ("x", "X", "X", "")
    if sysinfo.IS_LINUX:
        assert classify(kernel, 1000, None) == KIND_SYSTEM
    assert classify(daemon, 1000, None) == KIND_SYSTEM
    assert classify(mine, 1000, None) == KIND_BACKGROUND
    assert classify(mine, 1000, app) == KIND_APP
    assert classify(other, 1000, app) == KIND_BACKGROUND
    root_app = ProcInfo(pid=14, ppid=1, name="x", exe="/usr/bin/x", cmdline="x", uid=0)
    assert classify(root_app, 0, app) == KIND_APP


# -- system information ------------------------------------------------------------

def test_parse_meminfo():
    text = "MemTotal:       16000 kB\nDirty:  12 kB\nHugePages_Total:       0\n"
    info = sysinfo.parse_meminfo(text)
    assert info["MemTotal"] == 16000 * 1024
    assert info["Dirty"] == 12 * 1024
    assert info["HugePages_Total"] == 0


def test_parse_size():
    assert sysinfo.parse_size("32K") == 32 * 1024
    assert sysinfo.parse_size("8M") == 8 * 1024 ** 2
    assert sysinfo.parse_size("") == 0


def test_cache_sizes(tmp_path):
    for cpu in (0, 1):
        for idx, (level, ctype, size, shared) in enumerate(
                [("1", "Data", "32K", str(cpu)), ("1", "Instruction", "32K", str(cpu)),
                 ("2", "Unified", "1024K", str(cpu)), ("3", "Unified", "8192K", "0-1")]):
            d = tmp_path / "cpu{}".format(cpu) / "cache" / "index{}".format(idx)
            d.mkdir(parents=True)
            (d / "level").write_text(level)
            (d / "type").write_text(ctype)
            (d / "size").write_text(size)
            (d / "shared_cpu_list").write_text(shared)
    totals = sysinfo.linux_cache_sizes(str(tmp_path))
    assert totals == {"L1": 128 * 1024, "L2": 2048 * 1024, "L3": 8192 * 1024}


def test_net_utilization_assumes_gigabit_when_unknown():
    assert NetSample("eth0", sent_bps=125e5 / 2, recv_bps=125e5 / 2, speed_mbps=0).utilization == pytest.approx(10)
    assert NetSample("eth0", sent_bps=125e5, speed_mbps=100).utilization == pytest.approx(100)


# -- sampler (real system) -----------------------------------------------------------

def test_sampler_produces_rates():
    sampler = Sampler(registry=apps.AppRegistry([]))
    first = sampler.sample()
    assert first.interval == 0
    time.sleep(0.2)
    snap = sampler.sample()
    assert snap.interval > 0
    assert os.getpid() in snap.procs
    me = snap.procs[os.getpid()]
    assert me.mem_rss > 0 and me.threads >= 1
    assert 0 <= snap.cpu.total <= 100
    assert len(snap.cpu.per_cpu) >= 1
    assert snap.mem.total > 0 and 0 <= snap.mem.percent <= 100
    assert snap.threads > 0
    assert snap.uptime > 0


# -- services ---------------------------------------------------------------------------

SYSTEMCTL_SHOW = """Id=ssh.service
Description=OpenBSD Secure Shell server
LoadState=loaded
ActiveState=active
SubState=running
MainPID=812
Slice=system.slice
UnitFileState=enabled

Id=missing.service
Description=missing.service
LoadState=not-found
ActiveState=inactive
SubState=dead
MainPID=0

Id=cron.service
Description=Regular background program processing daemon
LoadState=loaded
ActiveState=inactive
SubState=dead
MainPID=0
Slice=system.slice
UnitFileState=disabled
"""


def test_parse_systemctl_show():
    svcs = services.parse_systemctl_show(SYSTEMCTL_SHOW)
    assert [s.name for s in svcs] == ["cron", "ssh"]
    ssh = svcs[1]
    assert ssh.status == "Running" and ssh.pid == 812 and ssh.group == "system"
    assert svcs[0].status == "Stopped" and svcs[0].pid == 0
    assert services.services_by_pid(svcs) == {812: ["ssh"]}


def test_parse_launchctl_list():
    text = "PID\tStatus\tLabel\n123\t0\tcom.apple.Finder\n-\t0\tcom.example.agent\n"
    svcs = services.parse_launchctl_list(text)
    assert svcs[0].name == "com.apple.Finder" and svcs[0].status == "Running" and svcs[0].pid == 123
    assert svcs[1].status == "Stopped"


# -- startup ------------------------------------------------------------------------------

def test_xdg_autostart_override(tmp_path):
    system = tmp_path / "etc" / "autostart"
    user = tmp_path / "home" / "autostart"
    system.mkdir(parents=True)
    (system / "agent.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Agent\nExec=agent --daemon\n")
    (system / "off.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Off\nExec=off\nX-GNOME-Autostart-enabled=false\n")
    items = {i.id: i for i in startup.list_xdg([str(user), str(system)])}
    assert items["agent.desktop"].enabled and not items["off.desktop"].enabled

    startup.set_xdg_enabled(items["agent.desktop"], False, user_dir=str(user))
    assert "Hidden=true" in (user / "agent.desktop").read_text()
    items = {i.id: i for i in startup.list_xdg([str(user), str(system)])}
    assert not items["agent.desktop"].enabled
    assert items["agent.desktop"].command == "agent --daemon"

    startup.set_xdg_enabled(items["off.desktop"], True, user_dir=str(user))
    items = {i.id: i for i in startup.list_xdg([str(user), str(system)])}
    assert items["off.desktop"].enabled


# -- app history -----------------------------------------------------------------------------

def test_app_history_accumulates_and_persists(tmp_path):
    path = tmp_path / "hist.json"
    hist = history.AppHistory(str(path))

    def snap(cpu, read):
        p = ProcInfo(pid=5, name="editor", create_time=1.0, kind=KIND_APP, app_id="ed", app_name="Editor",
                     cpu_time=cpu, io_read=read)
        return Snapshot(procs={5: p})

    hist.update(snap(10.0, 100))
    assert hist.apps == {}  # first sighting only establishes a baseline
    hist.update(snap(12.5, 400))
    assert hist.apps["ed"]["cpu"] == pytest.approx(2.5)
    assert hist.apps["ed"]["read"] == 300
    assert list(hist.entries()) == ["ed"]
    assert hist.entries(all_processes=True)["proc:editor"]["cpu"] == pytest.approx(2.5)
    hist.save()
    data = json.loads(path.read_text())
    assert data["apps"]["ed"]["name"] == "Editor"
    assert history.AppHistory(str(path)).apps["ed"]["read"] == 300
    hist.clear()
    assert history.AppHistory(str(path)).apps == {}


def test_run_new_task_opens_folders(monkeypatch, tmp_path):
    from taskmanager.backend import actions
    opened = []
    monkeypatch.setattr(actions, "open_path", opened.append)
    monkeypatch.setattr(actions.subprocess, "Popen", lambda *a, **k: pytest.fail("should not execute"))
    actions.run_new_task(str(tmp_path))
    actions.run_new_task("https://example.com")
    assert opened == [str(tmp_path), "https://example.com"]


def test_startup_type(tmp_path):
    system = tmp_path / "etc"
    user = tmp_path / "home"
    system.mkdir()
    user.mkdir()
    (system / "a.desktop").write_text("[Desktop Entry]\nType=Application\nName=A\nExec=a\n")
    (user / "b.desktop").write_text("[Desktop Entry]\nType=Application\nName=B\nExec=b\n")
    items = {i.id: i for i in startup.list_xdg([str(user), str(system)])}
    assert items["a.desktop"].source == "Autostart (system)"
    assert items["b.desktop"].source == "Autostart (user)"
