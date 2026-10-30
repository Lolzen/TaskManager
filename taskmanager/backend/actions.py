"""Process actions: end process, end tree, priority, affinity, run new task."""

import os
import shlex
import shutil
import subprocess
import sys

import psutil

# Windows priority classes mapped onto UNIX nice values.
PRIORITIES = [
    ("Realtime", -20),
    ("High", -10),
    ("Above Normal", -5),
    ("Normal", 0),
    ("Below Normal", 5),
    ("Low", 19),
]


def priority_name(nice):
    best = min(PRIORITIES, key=lambda p: abs(p[1] - nice))
    return best[0]


def end_process(pid, force=False):
    proc = psutil.Process(pid)
    if force:
        proc.kill()
    else:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except psutil.TimeoutExpired:
            proc.kill()


def end_process_tree(pid):
    proc = psutil.Process(pid)
    procs = proc.children(recursive=True) + [proc]
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(procs, timeout=2)
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def set_priority(pid, nice):
    psutil.Process(pid).nice(nice)


def suspend(pid):
    psutil.Process(pid).suspend()


def resume(pid):
    psutil.Process(pid).resume()


def supports_affinity():
    return hasattr(psutil.Process, "cpu_affinity")


def get_affinity(pid):
    return psutil.Process(pid).cpu_affinity()


def set_affinity(pid, cpus):
    psutil.Process(pid).cpu_affinity(list(cpus))


def open_path(path):
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    if not shutil.which(opener):
        raise OSError("'{}' is not available".format(opener))
    subprocess.Popen([opener, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def open_file_location(exe):
    if not exe:
        raise OSError("The executable path of this process is not accessible.")
    open_path(os.path.dirname(exe))


def run_new_task(command, elevated=False):
    """Start ``command`` detached from Task Manager (File > Run new task)."""
    args = shlex.split(command)
    if not args:
        raise ValueError("No command given")
    target = os.path.expanduser(args[0])
    is_document = os.path.isdir(target) or (os.path.isfile(target) and not os.access(target, os.X_OK))
    if len(args) == 1 and (is_document or "://" in target):
        open_path(target)  # documents, folders and URLs behave like the Windows Run box
        return
    if elevated:
        tool = shutil.which("pkexec") or shutil.which("sudo")
        if tool is None:
            raise OSError("Neither pkexec nor sudo is available")
        args = [tool] + args
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


RESOURCE_MONITORS = [
    ["gnome-system-monitor"],
    ["plasma-systemmonitor"],
    ["ksysguard"],
    ["mate-system-monitor"],
    ["xfce4-taskmanager"],
    ["lxtask"],
    ["open", "-a", "Activity Monitor"],
]


def open_resource_monitor():
    for cmd in RESOURCE_MONITORS:
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return
    for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
        if shutil.which(term):
            mon = shutil.which("htop") or shutil.which("top")
            if mon:
                subprocess.Popen([term, "-e", mon], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                return
    raise OSError("No resource monitor application was found.")


# -- top-level windows (Windows 7 *Applications* tab) ------------------------

def list_windows():
    """Return ``[(window_id, pid, title)]`` using wmctrl on X11, else ``None``."""
    if not shutil.which("wmctrl") or not os.environ.get("DISPLAY"):
        return None
    try:
        out = subprocess.run(["wmctrl", "-lp"], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    windows = []
    for line in out.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4 or parts[1] == "-1":  # sticky panels/desktops
            continue
        title = parts[4] if len(parts) > 4 else ""
        windows.append((parts[0], int(parts[2]) if parts[2].isdigit() else 0, title))
    return windows


def activate_window(window_id):
    if shutil.which("wmctrl"):
        subprocess.run(["wmctrl", "-ia", window_id], timeout=2, check=False)


def close_window(window_id):
    if shutil.which("wmctrl"):
        subprocess.run(["wmctrl", "-ic", window_id], timeout=2, check=False)


def logoff_session(user):
    """Terminate a login session (Users tab > Log off)."""
    if shutil.which("loginctl") and user.terminal:
        out = subprocess.run(["loginctl", "list-sessions", "--no-legend"], capture_output=True, text=True)
        for line in out.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2] == user.name and user.terminal in line:
                subprocess.run(["loginctl", "terminate-session", parts[0]], check=False)
                return
    if user.pid:
        psutil.Process(user.pid).terminate()
    else:
        raise OSError("Cannot determine the session leader for {}".format(user.name))


def send_message(user, text):
    """Users tab > Send Message, using write(1) to the user's terminal."""
    if not shutil.which("write"):
        raise OSError("write(1) is not installed")
    args = ["write", user.name] + ([user.terminal] if user.terminal else [])
    proc = subprocess.run(args, input=text + "\n", capture_output=True, text=True, timeout=5)
    if proc.returncode != 0:
        raise OSError(proc.stderr.strip() or "write failed")
