#!/bin/sh
# Test a built AppImage (or an extracted AppDir) on the current distribution.
# Run as root in a container of that distribution. It checks:
#   1. --version
#   2. smoke_test.py with the bundled interpreter (offscreen: every layout,
#      Tux mode, light and dark)
#   3. the real launcher on an X server with only the basic desktop libraries,
#      so the bundled fallback X11 libraries are used
#   4. the same with the distribution's own X11 helper libraries installed,
#      which then win over the bundled ones; a bundled library clashing with
#      the host's (as libxkbcommon-x11 once did) crashes here
set -eu
TARGET=$(readlink -f "$1")
HERE=$(cd "$(dirname "$0")" && pwd)
. /etc/os-release
echo "== $PRETTY_NAME"

install() {
  case "$ID" in
    ubuntu|debian) DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "$@" >/dev/null ;;
    fedora) dnf install -y -q "$@" >/dev/null ;;
    arch) pacman -S --noconfirm --needed "$@" >/dev/null ;;
    void) xbps-install -y "$@" >/dev/null ;;
  esac
}

# what any desktop has (GL, fonts, keyboard, D-Bus, GLib) plus a headless X server
case "$ID" in
  ubuntu|debian)
    apt-get update -qq
    install xvfb xauth libegl1 libgl1 libfontconfig1 libxkbcommon0 libdbus-1-3 libx11-xcb1
    install libglib2.0-0t64 2>/dev/null || install libglib2.0-0
    FULL_X="libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxkbcommon-x11-0
            libxcb-util1 libxcb-shape0 libxcb-xkb1 libxcb-randr0 libxcb-render0 libxcb-shm0 libxcb-sync1 libxcb-xfixes0" ;;
  fedora)
    install xorg-x11-server-Xvfb mesa-libEGL mesa-libGL fontconfig libxkbcommon dbus-libs glib2 libX11-xcb
    FULL_X="libxcb xcb-util xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-wm libxkbcommon-x11" ;;
  arch)
    pacman -Sy >/dev/null
    install xorg-server-xvfb libglvnd mesa fontconfig libxkbcommon dbus glib2 libx11
    FULL_X="libxcb xcb-util xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-wm libxkbcommon-x11" ;;
  void)
    xbps-install -Syu xbps >/dev/null
    install xorg-server-xvfb libglvnd mesa fontconfig libxkbcommon dbus-libs glib libX11
    FULL_X="libxcb xcb-util xcb-util-cursor xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-wm libxkbcommon-x11" ;;
  *)
    echo "unknown distribution $ID; assuming the libraries are installed"
    FULL_X="" ;;
esac

cd "$(mktemp -d)"
if [ -d "$TARGET" ]; then
  APPDIR=$TARGET
  LAUNCH=$APPDIR/AppRun
else
  "$TARGET" --appimage-extract >/dev/null
  APPDIR=$PWD/squashfs-root
  LAUNCH=$TARGET
  export APPIMAGE_EXTRACT_AND_RUN=1  # containers have no FUSE
fi

echo "== --version"
QT_QPA_PLATFORM=offscreen "$LAUNCH" --version

echo "== smoke test with the bundled interpreter"
QT_QPA_PLATFORM=offscreen "$APPDIR/usr/python/bin/python3" -I "$HERE/smoke_test.py"

Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1 &
sleep 2
export DISPLAY=:99

gui() {
  echo "== on X11 ($1)"
  status=0
  timeout 8 "$LAUNCH" --win10 --tux --theme dark > gui.log 2>&1 || status=$?
  grep -v "propagateSizeHints" gui.log || true
  if [ "$status" -ne 124 ]; then
    echo "the application exited early with status $status ($1)" >&2
    exit 1
  fi
  if grep -qE "Traceback|Fatal Python error|Could not load the Qt platform plugin" gui.log; then
    echo "the application reported an error ($1)" >&2
    exit 1
  fi
}

gui "basic libraries only, bundled fallbacks in use"
if [ -n "$FULL_X" ]; then
  # shellcheck disable=SC2086
  install $FULL_X
  gui "the distribution's own X11 libraries"
fi
echo "== AppImage OK on $PRETTY_NAME"
