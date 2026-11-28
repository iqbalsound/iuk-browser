#!/usr/bin/env bash
# Usage: packaging/build-appimage.sh <version>      (run from the repository root, after PyInstaller: dist/iuk-browser/)
# Produces dist/iuk-browser-<version>-x86_64.AppImage: one file that runs on most Linux distributions (no apt/dnf needed).
#   chmod +x iuk-browser-*.AppImage && ./iuk-browser-*.AppImage
set -euo pipefail
VERSION="${1:?version}"
[ -x dist/iuk-browser/iuk-browser ] || { echo "run PyInstaller first (dist/iuk-browser/iuk-browser missing)"; exit 1; }
APPDIR=dist/IUK-Browser.AppDir
rm -rf "$APPDIR"; mkdir -p "$APPDIR/usr/lib"
cp -a dist/iuk-browser "$APPDIR/usr/lib/iuk-browser"
cat > "$APPDIR/AppRun" <<'RUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/iuk-browser/iuk-browser" "$@"
RUN
chmod +x "$APPDIR/AppRun"
sed "s/^Version=1.0/Version=1.0\nX-AppImage-Version=$VERSION/" packaging/linux/iuk-browser.desktop > "$APPDIR/iuk-browser.desktop"
cp branding/generated/hicolor/256x256/apps/iuk-browser.png "$APPDIR/iuk-browser.png"
ln -sf iuk-browser.png "$APPDIR/.DirIcon"
TOOL=dist/appimagetool
if [ ! -x "$TOOL" ]; then
  curl -fsSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$TOOL"
fi
# --appimage-extract-and-run: works on CI runners and containers without FUSE
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "dist/iuk-browser-$VERSION-x86_64.AppImage"
rm -rf "$APPDIR"
ls -lh "dist/iuk-browser-$VERSION-x86_64.AppImage"
