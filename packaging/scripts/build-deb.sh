#!/bin/sh
# Build, install and test the Debian/Ubuntu package. Run as root inside an
# ubuntu:24.04 (or newer) container with the source tree at $SRC.
set -eu
SRC=${SRC:-$(cd "$(dirname "$0")/../.." && pwd)}
OUT=${OUT:-$SRC/dist}
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq --no-install-recommends build-essential devscripts equivs lintian >/dev/null
rm -rf /tmp/deb-build && mkdir -p /tmp/deb-build "$OUT"
cp -r "$SRC" /tmp/deb-build/taskmanager && cd /tmp/deb-build/taskmanager
rm -rf debian dist && cp -r packaging/debian debian
find . -name __pycache__ -prune -exec rm -rf {} +
mk-build-deps -i -r -t "apt-get -y -qq --no-install-recommends" debian/control >/dev/null
dpkg-buildpackage -us -uc -b
cp ../taskmanager_*.deb "$OUT/"
echo "== lintian"; lintian --info ../taskmanager_*.deb || true

echo "== install"
apt-get install -y -qq --no-install-recommends "$OUT"/taskmanager_*_all.deb python3-pytest >/dev/null
taskmanager --version
echo "== tests against the installed package"
rm -rf /tmp/deb-tests && mkdir /tmp/deb-tests && cp -r "$SRC/tests" /tmp/deb-tests/
cd /tmp/deb-tests && QT_QPA_PLATFORM=offscreen python3 -m pytest -q -p no:cacheprovider tests
python3 -c "import taskmanager, taskmanager.qt as q; assert taskmanager.__file__.startswith('/usr/lib'), taskmanager.__file__; print('binding:', q.BINDING)"
