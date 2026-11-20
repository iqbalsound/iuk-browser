#!/usr/bin/env bash
# Usage: packaging/build-bundle.sh <linux|windows> <version>
# Packages IUK Browser as DEB+RPM (linux) or setup.exe+portable zip (windows).
#
# Input (pick one):
#   default                     downloads the current official Firefox ESR (quick, personal use, Mozilla-branded binaries)
#   FIREFOX_TARBALL=<file>      Linux: your own source build from build/build-source.sh (IUK-branded, publishable)
#   FIREFOX_ZIP=<file>          Windows: output of `./mach package` from a Windows source build
#   SOURCE_BUILD=1              set automatically by build/build-source.sh; skips the signature workaround
#
# Needs: curl zip tar xz (linux) | 7z or unzip, makensis (windows) | nfpm (deb/rpm). Run from the repo root.
set -euo pipefail
OS="${1:?linux|windows}"; VERSION="${2:?version}"
ROOT="$(pwd)"; DIST="$ROOT/dist"; STAGE="$DIST/stage/$OS"; GEN="$ROOT/branding/generated"
XPI="$DIST/iuk-browser@iuk.local.xpi"
rm -rf "$STAGE"; mkdir -p "$DIST" "$STAGE"

# 1. extension -> .xpi
( cd extension && rm -f "$XPI" && zip -qr "$XPI" . -x '*.DS_Store' )

# 2. base Gecko
if [ "$OS" = linux ]; then
  APP="$STAGE/usr/lib/iuk-browser"
  mkdir -p "$APP" "$STAGE/usr/bin" "$STAGE/usr/share/applications"
  if [ -n "${FIREFOX_TARBALL:-}" ]; then
    tar -xf "$FIREFOX_TARBALL" -C "$APP" --strip-components=1
  else
    curl -fsSL -o "$DIST/ff.tar" "https://download.mozilla.org/?product=firefox-esr-latest-ssl&os=linux64&lang=en-US"
    tar -xf "$DIST/ff.tar" -C "$APP" --strip-components=1
  fi
  XPI_URL="file:///usr/lib/iuk-browser/distribution/extensions/iuk-browser@iuk.local.xpi"
  install -m755 packaging/iuk-browser-launcher.sh "$STAGE/usr/bin/iuk-browser"
  install -m644 packaging/iuk-browser.desktop "$STAGE/usr/share/applications/iuk-browser.desktop"
  # icons: system theme (taskbar, minimized window, launcher, alt-tab) ...
  mkdir -p "$STAGE/usr/share/icons" && cp -r "$GEN/hicolor" "$STAGE/usr/share/icons/"
  # ... and the window icons Gecko itself loads (also correct when starting the binary directly)
  ICONDIR="$APP/browser/chrome/icons/default"
  if [ -d "$ICONDIR" ]; then
    for s in 16 32 48 64 128; do cp "$GEN/hicolor/${s}x${s}/apps/iuk-browser.png" "$ICONDIR/default$s.png"; done
  fi
else
  APP="$STAGE"
  if [ -n "${FIREFOX_ZIP:-}" ]; then
    rm -rf "$DIST/ffx"; unzip -q "$FIREFOX_ZIP" -d "$DIST/ffx"; cp -r "$DIST/ffx/firefox/." "$APP/"
  else
    curl -fsSL -o "$DIST/ff-setup.exe" "https://download.mozilla.org/?product=firefox-esr-latest-ssl&os=win64&lang=en-US"
    7z x -y -o"$DIST/ffx" "$DIST/ff-setup.exe" >/dev/null; cp -r "$DIST/ffx/core/." "$APP/"
  fi
  XPI_URL="file:///C:/Program%20Files/IUK%20Browser/distribution/extensions/iuk-browser@iuk.local.xpi"
fi

# 3. IUK Browser distribution layer
mkdir -p "$APP/distribution/extensions"
cp "$XPI" "$APP/distribution/extensions/"
sed "s|@XPI_URL@|$XPI_URL|" distribution/policies.json > "$APP/distribution/policies.json"
if [ "${SOURCE_BUILD:-0}" != 1 ]; then   # official binaries need the unsigned-add-on workaround
  mkdir -p "$APP/defaults/pref"
  cp distribution/autoconfig.js "$APP/defaults/pref/autoconfig.js"
  cp distribution/iuk-browser.cfg "$APP/iuk-browser.cfg"
fi

# 4. package
if [ "$OS" = linux ]; then
  export VERSION MAINTAINER="${MAINTAINER:-IUK Browser <noreply@example.com>}" GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-iqbalsound/iuk-browser}"
  nfpm package -f packaging/nfpm.yaml -p deb -t "$DIST/"
  nfpm package -f packaging/nfpm.yaml -p rpm -t "$DIST/"
else
  DIRECT_FLAG=""; [ "${SOURCE_BUILD:-0}" = 1 ] && DIRECT_FLAG="-DDIRECT=1"
  ( cd packaging && makensis -DVERSION="$VERSION" -DSTAGE="dist/stage/windows" $DIRECT_FLAG installer.nsi )
  cp "$GEN"/*.ico "$APP/"
  ( cd "$STAGE" && zip -qr "$DIST/iuk-browser-$VERSION-win64-portable.zip" . )
fi
ls -lh "$DIST"
