#!/bin/sh
# Build dist/TaskManager-<version>-<arch>.AppImage.
#
# The AppImage bundles a relocatable CPython (python-build-standalone),
# psutil and PySide6 from PyPI, and the X11 helper libraries Qt's xcb plugin
# needs but minimal systems lack. PySide6's wheels need glibc 2.34, so the
# result runs on Ubuntu 22.04, Debian 12, Fedora 35, Arch, Void (glibc) and
# newer.
#
# Run as root on Ubuntu 22.04 (CI uses an ubuntu:22.04 container); the
# script installs its build dependencies with apt. It downloads from GitHub
# (python-build-standalone, appimagetool and the AppImage runtime) and PyPI.
#
# Overrides: PYTHON_URL (+ PYTHON_SHA256), APPIMAGETOOL_URL, RUNTIME_FILE,
# PYTHON_SERIES (default 3.12), GITHUB_TOKEN (avoids API rate limits).
set -eu
SRC=${SRC:-$(cd "$(dirname "$0")/../.." && pwd)}
OUT=${OUT:-$SRC/dist}
ARCH=${ARCH:-$(uname -m)}
PYTHON_SERIES=${PYTHON_SERIES:-3.12}
WORK=${WORK:-/tmp/appimage-build}
APPIMAGETOOL_URL=${APPIMAGETOOL_URL:-https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage}
# Qt 6's xcb platform plugin links these; they are missing on many minimal installs
BUNDLED_LIBS="libxcb-cursor.so.0 libxcb-icccm.so.4 libxcb-image.so.0 libxcb-keysyms.so.1 libxcb-render-util.so.0 libxkbcommon-x11.so.0"

if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends ca-certificates curl python3 file desktop-file-utils librsvg2-bin \
      libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxkbcommon-x11-0 >/dev/null
fi

version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/taskmanager/__init__.py")
rm -rf "$WORK" && mkdir -p "$WORK" "$OUT"
cd "$WORK"
APPDIR=$WORK/AppDir

echo "== relocatable Python $PYTHON_SERIES ($ARCH)"
if [ -z "${PYTHON_URL:-}" ]; then
  curl -fsSL ${GITHUB_TOKEN:+-H "Authorization: Bearer $GITHUB_TOKEN"} \
      https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest -o release.json
  # prints the tarball URL and the URL of its checksum (a .sha256 file or SHA256SUMS)
  set -- $(python3 - "$PYTHON_SERIES" "$ARCH" release.json <<'PY'
import json, re, sys
series, arch, path = sys.argv[1:]
assets = {a["name"]: a["browser_download_url"] for a in json.load(open(path))["assets"]}
pattern = re.compile(r"cpython-{}\.\d+\+\d+-{}-unknown-linux-gnu-install_only\.tar\.gz$".format(
    re.escape(series), re.escape(arch)))
name = next(n for n in sorted(assets) if pattern.match(n))
print(assets[name], assets.get(name + ".sha256") or assets["SHA256SUMS"])
PY
)
  PYTHON_URL=$1
  SUMS_URL=$2
  curl -fsSL "$SUMS_URL" -o python.sums
  PYTHON_SHA256=$(awk -v n="$(basename "$PYTHON_URL" | sed 's/%2B/+/g')" 'NF == 1 {print $1} $2 == n {print $1}' python.sums | head -n1)
fi
echo "$PYTHON_URL"
curl -fsSL "$PYTHON_URL" -o python.tar.gz
if [ -n "${PYTHON_SHA256:-}" ]; then
  echo "$PYTHON_SHA256  python.tar.gz" | sha256sum -c -
else
  echo "warning: no checksum for $PYTHON_URL" >&2
fi
mkdir -p "$APPDIR/usr"
tar -xzf python.tar.gz -C "$APPDIR/usr"  # -> usr/python
PY="$APPDIR/usr/python/bin/python3"

echo "== Task Manager $version with its dependencies"
cp -r "$SRC" "$WORK/src"  # pip builds in the source tree, which may be read-only
rm -rf "$WORK/src/build" "$WORK/src/dist" "$WORK/src"/*.egg-info
"$PY" -m pip install --no-cache-dir --no-warn-script-location --disable-pip-version-check "$WORK/src"
"$PY" -c "import taskmanager, psutil, PySide6; print('taskmanager', taskmanager.__version__, 'PySide6', PySide6.__version__)"

echo "== trimming"
site=$("$PY" -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
stdlib=$("$PY" -c "import sysconfig; print(sysconfig.get_paths()['stdlib'])")
# Qt developer tools, headers, bindings sources, QML and translations are not needed at run time
for f in assistant designer linguist lrelease lupdate qmlformat qmllint qmlls qmlcachegen qmltyperegistrar \
         rcc uic balsam balsamui qsb svgtoqml include typesystems glue scripts Qt/qml Qt/translations; do
  rm -rf "$site/PySide6/$f"
done
rm -rf "$stdlib/test" "$stdlib/idlelib" "$stdlib/tkinter" "$stdlib/turtledemo" "$stdlib/ensurepip" \
       "$APPDIR/usr/python/lib/libtcl"* "$APPDIR/usr/python/lib/libtk"* "$APPDIR/usr/python/lib/tcl"* \
       "$APPDIR/usr/python/share" "$APPDIR/usr/python/include"
"$PY" -m pip uninstall -y -q pip setuptools wheel 2>/dev/null || true
"$PY" -m compileall -q -j 0 "$site/taskmanager" >/dev/null

echo "== bundled libraries"
mkdir -p "$APPDIR/usr/lib"
for lib in $BUNDLED_LIBS; do
  path=$(ldconfig -p | awk -v l="$lib" '$1 == l && /x86-64|aarch64|AArch64/ {print $NF; exit}')
  if [ -n "$path" ]; then
    cp -L "$path" "$APPDIR/usr/lib/$lib" && echo "$lib"
  else
    echo "warning: $lib not found, not bundled" >&2
  fi
done

echo "== AppDir metadata"
install -m 755 "$SRC/packaging/appimage/AppRun" "$APPDIR/AppRun"
install -m 644 "$SRC/data/taskmanager.desktop" "$APPDIR/taskmanager.desktop"
# appimagetool wants a PNG icon (it derives .DirIcon from it); keep the SVG for desktop integration
rsvg-convert -w 256 -h 256 "$SRC/data/taskmanager.svg" -o "$APPDIR/taskmanager.png"
install -Dm644 "$APPDIR/taskmanager.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/taskmanager.png"
install -Dm644 "$SRC/data/taskmanager.desktop" "$APPDIR/usr/share/applications/taskmanager.desktop"
install -Dm644 "$SRC/data/taskmanager.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/taskmanager.svg"
install -Dm644 "$SRC/LICENSE" "$APPDIR/usr/share/licenses/taskmanager/LICENSE"
command -v desktop-file-validate >/dev/null 2>&1 && desktop-file-validate "$APPDIR/taskmanager.desktop"

echo "== appimagetool"
curl -fsSL "$APPIMAGETOOL_URL" -o appimagetool
chmod +x appimagetool
target="$OUT/TaskManager-$version-$ARCH.AppImage"
# no FUSE inside containers: let the tool unpack itself
ARCH=$ARCH APPIMAGE_EXTRACT_AND_RUN=1 ./appimagetool --no-appstream ${RUNTIME_FILE:+--runtime-file "$RUNTIME_FILE"} \
    "$APPDIR" "$target"
ls -lh "$target"
