# Distribution packages

| Distribution | Recipe | Qt binding | Tested |
|---|---|---|---|
| Ubuntu 24.04 LTS and newer | `debian/` (dpkg-buildpackage, pybuild) | `python3-pyqt6` (or `python3-pyside6.qtwidgets` where available) | built, installed, test suite run |
| Arch Linux | `arch/PKGBUILD` (makepkg) | `pyside6` (or `python-pyqt6`) | built, installed, test suite run with both bindings, `namcap` |
| Void Linux | `void/srcpkgs/taskmanager/template` (xbps-src) | `python3-pyside6-widgets` | built with `xbps-src -Q` (tests run during the build), installed, `xlint` |

Ubuntu 22.04 and older are not supported. They package no Qt 6 bindings for
Python (neither PyQt6 nor PySide6). The AppImage below covers them.

Each recipe also installs the icon (`taskmanager.svg`, hicolor theme).

## AppImage

`appimage/build-appimage.sh` builds `dist/TaskManager-<version>-<arch>.AppImage`.
The AppImage contains:

* a relocatable CPython from
  [python-build-standalone](https://github.com/astral-sh/python-build-standalone),
  checked against its published SHA-256;
* psutil and PySide6 from PyPI;
* the X11 helper libraries Qt's xcb plugin needs but minimal systems lack
  (`libxcb-cursor` and friends).

`AppRun` starts the app with `python3 -I`, so the host's `PYTHONPATH` and
site-packages cannot interfere. Programs Task Manager starts for you get the
original `LD_LIBRARY_PATH` back.

* **Requirements:** PySide6's wheels need glibc 2.34+. That covers Ubuntu
  22.04, Debian 12, Fedora 35, Arch, Void (glibc) and newer, but not musl.
  The usual desktop libraries must be present: EGL/GL, fontconfig,
  xkbcommon, D-Bus, GLib.
* **How to build:** run the script as root in an `ubuntu:22.04` container
  (see the main README). It downloads python-build-standalone,
  `appimagetool` and the AppImage runtime from GitHub, and the Python
  packages from PyPI.
* **Overrides:** `PYTHON_URL`/`PYTHON_SHA256`, `PYTHON_SERIES`,
  `APPIMAGETOOL_URL` and `RUNTIME_FILE` pin or replace those downloads.
* **Testing:** `appimage/test-appimage.sh <file>` tests a built AppImage
  inside a container of any supported distribution. It runs `--version`,
  then `smoke_test.py` with the bundled interpreter (every layout, Tux mode,
  light and dark), then the real launcher. CI does this on Ubuntu 22.04 and
  24.04, Debian 12, Fedora, Arch and Void.

Each recipe installs:

* the `taskmanager` command;
* `/usr/share/applications/taskmanager.desktop`, which offers Windows 7/8/10
  and Tux mode as launcher actions;
* the `taskmanager(1)` man page;
* the license.

## Building locally

Every script builds the package, installs it, and runs the test suite
against the installed copy. The finished package is written to `dist/`.

```bash
docker run --rm -v "$PWD":/src -e SRC=/src ubuntu:24.04 /src/packaging/scripts/build-deb.sh
```

```bash
docker run --rm -v "$PWD":/src -e SRC=/src archlinux:latest /src/packaging/scripts/build-arch.sh
```

```bash
docker run --rm --privileged -v /dev:/dev -v "$PWD":/src -e SRC=/src ghcr.io/void-linux/void-glibc-full /src/packaging/scripts/build-void.sh
```

Void's `xbps-src` needs `--privileged` for its build chroot. Behind a
TLS-intercepting proxy, pass `-e EXTRA_CA_CERT=/path/in/container.crt` so the
chroot trusts the proxy too. The same three jobs, plus the AppImage build and its tests, run in GitHub
Actions (`.github/workflows/ci.yml`) on every push and pull request. When a
`v*` tag is pushed, the `.deb`, Arch package, Void package and AppImage are
attached to the GitHub release.

Installing the result:

```bash
sudo apt install ./dist/taskmanager_1.0.0-1_all.deb
```

```bash
sudo pacman -U dist/taskmanager-1.0.0-1-any.pkg.tar.zst
```

```bash
sudo xbps-install -R dist taskmanager
```

(`xbps-install -R` needs a repository index. Running `xbps-rindex -a dist/*.xbps` creates one.)

## Before submitting to the distributions

All three recipes download the release tarball
`https://github.com/Lolzen/TaskManager/archive/refs/tags/v1.0.0.tar.gz`. So
first:

1. **Tag and publish the release** `v1.0.0` on GitHub.
2. **Fill in the checksums** from that tarball:
   * Arch: `updpkgsums` in `arch/`, which replaces `sha256sums=('SKIP')`.
   * Void: `xgensum -i taskmanager` in a void-packages checkout, which
     replaces the zero placeholder.
3. **Set a real maintainer e-mail.** The recipes use
   `lolzen@users.noreply.github.com`. Void's `xlint` rejects it ("maintainer
   needs a valid address"), and Debian/Launchpad need an address you can
   receive mail at.

## Submitting

Only Void takes pull requests. The other two use their own processes:

* **Ubuntu.**
  * *PPA (practical route):* create a PPA on Launchpad and upload a source
    package built with `debuild -S -sa`, signed with a GPG key registered
    there. The changelog already targets `noble`; add a changelog entry per
    Ubuntu release you upload for.
  * *Official archive:* new packages enter Ubuntu through Debian. That means
    filing an *Intent To Package* (ITP) bug against `wnpp`, closing it from
    `debian/changelog`, and finding a sponsor on `debian-mentors`.
* **Arch: AUR (not a pull request).**
  1. Log in to aur.archlinux.org with an SSH key.
  2. Clone `ssh://aur@aur.archlinux.org/taskmanager.git`.
  3. Add `PKGBUILD` and a `.SRCINFO` (`makepkg --printsrcinfo > .SRCINFO`), then push.

  Check first that the name `taskmanager` is still free in the AUR and in the
  official repositories.
* **Void: pull request to `void-linux/void-packages`.**
  1. Copy `void/srcpkgs/taskmanager/` into a fork.
  2. Commit as `New package: taskmanager-1.0.0` and open a pull request.

  Void's CONTRIBUTING.md states requirements a new package must meet:
  * at least one of: installed system-wide, compiled, or required by another
    package;
  * an "established and mature release history" (new projects are "not good
    candidates");
  * preferably submitted by someone other than the developer.

  A pull request for a project on its first release is therefore likely to
  be declined for now. Until then, the template works in a local
  void-packages checkout.
