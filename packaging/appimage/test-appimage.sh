#!/bin/sh
# Test a built AppImage on the current distribution (run as root in a
# container of that distribution): installs the libraries a desktop system
# always has, then starts the AppImage three ways.
set -eu
APPIMAGE=$(readlink -f "$1")
HERE=$(cd "$(dirname "$0")" && pwd)
. /etc/os-release
echo "== $PRETTY_NAME"

# graphics, fonts, keyboard, D-Bus and GLib: present on any desktop, absent in containers
case "$ID" in
  ubuntu|debian)
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends libegl1 libgl1 libfontconfig1 libxkbcommon0 libdbus-1-3 \
        libx11-xcb1 >/dev/null
    apt-get install -y -qq --no-install-recommends libglib2.0-0t64 >/dev/null 2>&1 ||
        apt-get install -y -qq --no-install-recommends libglib2.0-0 >/dev/null ;;
  fedora)
    dnf install -y -q mesa-libEGL mesa-libGL fontconfig libxkbcommon dbus-libs glib2 libX11-xcb >/dev/null ;;
  arch)
    pacman -Sy --noconfirm --needed libglvnd mesa fontconfig libxkbcommon dbus glib2 libx11 >/dev/null ;;
  void)
    xbps-install -Syu xbps >/dev/null && xbps-install -y libglvnd mesa fontconfig libxkbcommon dbus-libs glib libX11 >/dev/null ;;
  *)
    echo "unknown distribution $ID; assuming the libraries are installed" ;;
esac

export QT_QPA_PLATFORM=offscreen
cd "$(mktemp -d)"

echo "== --version"
"$APPIMAGE" --appimage-extract-and-run --version

echo "== smoke test with the bundled interpreter"
"$APPIMAGE" --appimage-extract >/dev/null
squashfs-root/usr/python/bin/python3 -I "$HERE/smoke_test.py"

echo "== the real launcher for 5 seconds"
status=0
timeout 5 "$APPIMAGE" --appimage-extract-and-run --win10 --tux --theme dark 2> stderr.log || status=$?
cat stderr.log
if [ "$status" -ne 124 ]; then
  echo "the application exited early with status $status" >&2
  exit 1
fi
if grep -q "Traceback" stderr.log; then
  echo "the application printed a traceback" >&2
  exit 1
fi
echo "== AppImage OK on $PRETTY_NAME"
