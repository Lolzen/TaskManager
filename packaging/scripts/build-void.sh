#!/bin/sh
# Build the Void package with xbps-src, install it and run the tests.
# Run as root inside a privileged ghcr.io/void-linux/void-glibc-full container
# (xbps-src needs user namespaces) with the source tree at $SRC.
set -eu
SRC=${SRC:-$(cd "$(dirname "$0")/../.." && pwd)}
OUT=${OUT:-$SRC/dist}
VP=${VOID_PACKAGES:-/tmp/void-packages}

xbps-install -Syu xbps >/dev/null && xbps-install -yu >/dev/null
xbps-install -y bash git sudo python3 xtools >/dev/null
id builder >/dev/null 2>&1 || useradd -G xbuilder -m builder
[ -d "$VP/.git" ] || git clone -q --depth 1 https://github.com/void-linux/void-packages "$VP"
mkdir -p "$OUT"

tarball=$(python3 "$SRC/packaging/scripts/make-tarball.py" /tmp)
version=$(sed -n 's/^version=//p' "$SRC/packaging/void/srcpkgs/taskmanager/template")
sum=$(sha256sum "$tarball" | cut -d' ' -f1)
mkdir -p "$VP/srcpkgs/taskmanager" "$VP/hostdir/sources/taskmanager-$version"
cp "$tarball" "$VP/hostdir/sources/taskmanager-$version/v$version.tar.gz"
# until a release is tagged the template carries a placeholder checksum
sed "s/^checksum=.*/checksum=$sum/" "$SRC/packaging/void/srcpkgs/taskmanager/template" \
    > "$VP/srcpkgs/taskmanager/template"
grep -q '^XBPS_CHROOT_CMD=' "$VP/etc/conf" 2>/dev/null || echo XBPS_CHROOT_CMD=uchroot >> "$VP/etc/conf"
chown -R builder "$VP"
cd "$VP"

echo "== xlint"
# the maintainer address is checked for deliverability; everything else must be clean
xlint srcpkgs/taskmanager/template | grep -v "maintainer needs a valid address" && exit 1 || true

sudo -u builder ./xbps-src binary-bootstrap
if [ -n "${EXTRA_CA_CERT:-}" ]; then
  # behind a TLS-intercepting proxy the build chroot must trust its CA as well
  for m in masterdir*; do
    mkdir -p "$m/usr/local/share/ca-certificates"
    awk -v d="$m/usr/local/share/ca-certificates" '/BEGIN CERTIFICATE/{n++} {print > (d "/extra-ca-" n ".crt")}' "$EXTRA_CA_CERT"
    chroot "$m" update-ca-certificates >/dev/null 2>&1 || true
  done
fi
sudo -u builder ./xbps-src -Q pkg taskmanager
cp hostdir/binpkgs/taskmanager-*.xbps "$OUT/"

echo "== install"
xbps-install -y -R hostdir/binpkgs taskmanager python3-pytest >/dev/null
taskmanager --version
rm -rf /tmp/void-tests && mkdir /tmp/void-tests && cp -r "$SRC/tests" /tmp/void-tests/
cd /tmp/void-tests && QT_QPA_PLATFORM=offscreen python3 -m pytest -q -p no:cacheprovider tests
