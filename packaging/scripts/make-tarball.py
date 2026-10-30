#!/usr/bin/env python3
"""Create dist/taskmanager-<version>.tar.gz laid out like GitHub's release tarball
(top directory ``TaskManager-<version>``), so the Arch and Void recipes can be
built from a working tree before a release is tagged."""

import os
import re
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKIP_DIRS = {".git", "__pycache__", "dist", "build", ".pytest_cache", ".pybuild", "debian"}


def version():
    with open(os.path.join(ROOT, "taskmanager", "__init__.py"), encoding="utf-8") as fh:
        return re.search(r'__version__ = "([^"]+)"', fh.read()).group(1)


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    ver = version()
    target = os.path.join(out_dir, "taskmanager-{}.tar.gz".format(ver))
    prefix = "TaskManager-{}".format(ver)
    with tarfile.open(target, "w:gz") as tar:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info"))
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                if os.path.abspath(path) == os.path.abspath(target):
                    continue
                tar.add(path, arcname=os.path.join(prefix, os.path.relpath(path, ROOT)))
    print(target)


if __name__ == "__main__":
    main()
