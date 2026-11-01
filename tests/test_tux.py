import os
import time

import pytest

from taskmanager.backend import linux, services, startup, sysinfo
from taskmanager.backend.apps import AppRegistry
from taskmanager.backend.sampler import Sampler

STAT = ("1234 (Web Content (x)) S 1000 1234 999 34816 1234 4194560 5120 0 7 0 120 30 0 0 20 0 21 0 "
        "8800 2147483648 50000 18446744073709551615 1 1 0 0 0 0 0 4096 1260 0 0 0 17 3 0 0 0 0 0")


def test_parse_stat_handles_spaces_in_name():
    stat = linux.parse_stat(STAT)
    assert stat["state"] == "S"
    assert stat["pgrp"] == 1234 and stat["session"] == 999
    assert stat["minflt"] == 5120 and stat["majflt"] == 7
    assert stat["vsize"] == 2147483648
    assert stat["processor"] == 3 and stat["policy"] == 0


def test_capabilities_and_cgroups():
    assert linux.describe_caps("0000000000000000") == "None"
    assert linux.describe_caps("000001ffffffffff") == "All"
    assert linux.describe_caps("0000000000003000") == "2 capabilities"
    path = "/user.slice/user-1000.slice/user@1000.service/app.slice/app-org.mozilla.firefox-1234.scope"
    assert linux.unit_from_cgroup(path) == "app-org.mozilla.firefox-1234.scope"
    assert linux.unit_from_cgroup("/system.slice/docker-abc.scope") == "docker-abc.scope"
    assert linux.container_from_cgroup("/system.slice/docker-abc.scope") == "Docker"
    assert linux.container_from_cgroup("/user.slice/snap.firefox.firefox-1.scope") == "Snap"
    assert linux.container_from_cgroup("/x", flatpak=True) == "Flatpak"
    assert linux.parse_cgroup("0::/system.slice/sshd.service\n") == "/system.slice/sshd.service"
    v1 = "12:pids:/\n1:name=systemd:/system.slice/cron.service\n0::/\n"
    assert linux.parse_cgroup(v1) == "/system.slice/cron.service"


def test_pressure_and_scheduler():
    text = "some avg10=1.50 avg60=0.75 avg300=0.10 total=123\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
    assert linux.parse_pressure(text) == {"some": (1.5, 0.75, 0.1), "full": (0.0, 0.0, 0.0)}
    assert linux.parse_scheduler("none [mq-deadline] kyber bfq\n") == "mq-deadline"


def test_read_proc_extras_from_fake_tree(tmp_path):
    base = tmp_path / "1234"
    (base / "fd").mkdir(parents=True)
    (base / "attr").mkdir()
    for fd in ("0", "1", "2"):
        os.symlink("/dev/null", str(base / "fd" / fd))
    (base / "stat").write_text(STAT)
    (base / "status").write_text("Name:\tx\nCapEff:\t0000000000000000\nSeccomp:\t2\nNoNewPrivs:\t1\n"
                                 "VmSwap:\t  12 kB\nvoluntary_ctxt_switches:\t40\nnonvoluntary_ctxt_switches:\t2\n")
    (base / "smaps_rollup").write_text("Rss: 900 kB\nPss: 500 kB\nPrivate_Clean: 100 kB\n"
                                       "Private_Dirty: 300 kB\nSwap: 16 kB\n")
    (base / "cgroup").write_text("0::/user.slice/user-1000.slice/session-2.scope\n")
    (base / "oom_score").write_text("667\n")
    (base / "oom_score_adj").write_text("200\n")
    (base / "attr" / "current").write_text("unconfined\n")
    ex = linux.read_proc_extras(1234, str(tmp_path))
    assert ex.state == "Sleeping" and ex.policy == "Normal"
    assert ex.uss == 400 * 1024 and ex.pss == 500 * 1024 and ex.swap == 16 * 1024
    assert ex.fds == 3
    assert ex.ctx_voluntary == 40 and ex.ctx_involuntary == 2
    assert ex.capabilities == "None" and ex.seccomp == "Filter" and ex.no_new_privs
    assert ex.unit == "session-2.scope" and ex.container == ""
    assert ex.oom_score == 667 and ex.oom_adj == 200
    assert ex.label == "unconfined"
    assert ex.last_cpu == 3 and ex.major_faults == 7


def test_missing_process_gives_empty_extras(tmp_path):
    ex = linux.read_proc_extras(99999, str(tmp_path))
    assert ex.state == "" and ex.fds == -1


@pytest.mark.skipif(not sysinfo.IS_LINUX, reason="Linux only")
def test_sampler_collects_tux_data():
    sampler = Sampler(registry=AppRegistry([]))
    sampler.tux = True
    sampler.sample()
    time.sleep(0.2)
    snap = sampler.sample()
    me = snap.procs[os.getpid()]
    assert me.tux is not None and me.tux.state in ("Running", "Sleeping")
    assert me.tux.fds > 0 and me.tux.uss > 0
    ex = snap.tux
    assert ex.static["Kernel"].startswith("Linux")
    assert len(ex.loadavg) == 3 and ex.meminfo.get("MemTotal", 0) > 0
    assert ex.file_handles[1] > 0


def test_tux_off_collects_nothing_extra():
    sampler = Sampler(registry=AppRegistry([]))
    sampler.sample()
    snap = sampler.sample()
    assert snap.tux is None
    assert all(p.tux is None for p in snap.procs.values())


def test_systemd_user_unit_files():
    text = ("pipewire.service           enabled  enabled\n"
            "syncthing.service          disabled enabled\n"
            "dbus.service               static   -\n"
            "foo@.service               enabled  enabled\n")
    items = startup.parse_user_unit_files(text)
    assert [(i.name, i.enabled, i.kind) for i in items] == [("pipewire", True, "systemd"),
                                                             ("syncthing", False, "systemd")]


def test_systemctl_show_tux_fields():
    text = ("Id=ssh.service\nDescription=SSH\nLoadState=loaded\nActiveState=active\nSubState=running\n"
            "MainPID=8\nType=notify\nNRestarts=2\nMemoryCurrent=4194304\nTasksCurrent=3\n"
            "CPUUsageNSec=[not set]\nUnitFileState=enabled\n")
    (svc,) = services.parse_systemctl_show(text)
    assert svc.type == "notify" and svc.restarts == 2 and svc.memory == 4194304 and svc.tasks == 3
    assert svc.cpu_ns == -1 and svc.sub_state == "running"
    text = text.replace("MemoryCurrent=4194304", "MemoryCurrent=18446744073709551615")
    assert services.parse_systemctl_show(text)[0].memory == -1
