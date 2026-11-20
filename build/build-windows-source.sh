#!/usr/bin/env bash
# Runs INSIDE the MozillaBuild shell on Windows. Builds Firefox ESR with the IUK branding overlay.
#   FIREFOX_REF=<tag> OVERLAY=/path/branding-overlay.tar.gz build/build-windows-source.sh
# Output: dist/firefox-*.win64.zip  (feed to: SOURCE_BUILD=1 FIREFOX_ZIP=... packaging/build-bundle.sh windows <version>)
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"; SRC="$REPO/.build/firefox"
REF="${FIREFOX_REF:?FIREFOX_REF is required}"; OVERLAY="${OVERLAY:?OVERLAY is required}"
mkdir -p "$REPO/.build" "$REPO/dist"
[ -d "$SRC/.git" ] || git clone --depth 1 --branch "$REF" https://github.com/mozilla-firefox/firefox "$SRC"
tar -xzf "$OVERLAY" -C "$SRC"
cp build/mozconfig.windows "$SRC/mozconfig"
cd "$SRC"
./mach --no-interactive bootstrap --application-choice=browser
./mach build
./mach package
cp obj-iuk-browser/dist/firefox-*.win64.zip "$REPO/dist/"
ls -lh "$REPO/dist"
