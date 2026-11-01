#!/bin/sh
# Build, install and test the Arch package with makepkg. Run as root inside an
# archlinux:latest container with the source tree at $SRC.
set -eu
SRC=${SRC:-$(cd "$(dirname "$0")/../.." && pwd)}
OUT=${OUT:-$SRC/dist}

pacman -Syu --noconfirm --needed base-devel namcap python python-psutil pyside6 python-pyqt6 \
    python-pytest python-build python-installer python-setuptools python-wheel >/dev/null
id builder >/dev/null 2>&1 || useradd -m builder
rm -rf /tmp/arch-build && mkdir -p /tmp/arch-build "$OUT"
python "$SRC/packaging/scripts/make-tarball.py" /tmp/arch-build >/dev/null
cp "$SRC/packaging/arch/PKGBUILD" /tmp/arch-build/
chown -R builder /tmp/arch-build
cd /tmp/arch-build
su builder -c "makepkg --noconfirm --cleanbuild"
echo "== namcap"; namcap PKGBUILD taskmanager-*.pkg.tar.zst || true
cp taskmanager-*.pkg.tar.zst "$OUT/"

echo "== install"
pacman -U --noconfirm taskmanager-*.pkg.tar.zst >/dev/null
taskmanager --version
rm -rf /tmp/arch-tests && mkdir /tmp/arch-tests && cp -r "$SRC/tests" /tmp/arch-tests/
cd /tmp/arch-tests
for binding in pyside6 pyqt6; do
  echo "== tests against the installed package ($binding)"
  TASKMANAGER_QT=$binding QT_QPA_PLATFORM=offscreen python -m pytest -q -p no:cacheprovider tests
done
