#!/usr/bin/env bash
# Builds IUK Browser from Firefox ESR source on Linux x86_64 and packages DEB + RPM.
# Needs ~40 GB free disk, 16 GB RAM, git, python3, curl, and 1-4 hours.
#   build/build-source.sh                       # latest ESR
#   FIREFOX_REF=FIREFOX_153_7_0esr_RELEASE build/build-source.sh
#   SKIP_PACKAGE=1 build/build-source.sh        # stop after ./mach package
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"; WORK="${WORK:-$REPO/.build}"; SRC="$WORK/firefox"
UPSTREAM="https://github.com/mozilla-firefox/firefox"

REF="${FIREFOX_REF:-$(git ls-remote --tags "$UPSTREAM" 'FIREFOX_*esr*_RELEASE' | awk '{print $2}' | sed 's#refs/tags/##' | sort -V | tail -1)}"
[ -n "$REF" ] || { echo "Could not determine an ESR tag; set FIREFOX_REF"; exit 1; }
FFVER="$(echo "$REF" | sed -E 's/^FIREFOX_([0-9]+)_([0-9]+)_([0-9]+)esr_RELEASE$/\1.\2.\3/; s/^FIREFOX_([0-9]+)_([0-9]+)esr_RELEASE$/\1.\2/')"
echo ">> Firefox source ref: $REF (version $FFVER)"

mkdir -p "$WORK"
if [ ! -d "$SRC/.git" ]; then
  git clone --depth 1 --branch "$REF" "$UPSTREAM" "$SRC"
else
  git -C "$SRC" fetch --depth 1 origin "refs/tags/$REF:refs/tags/$REF" && git -C "$SRC" checkout -f "$REF"
fi

echo ">> Rebranding the source tree"
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install -q -r branding/requirements.txt
"$WORK/venv/bin/python" branding/apply_to_source.py "$SRC"
cp build/mozconfig.linux "$SRC/mozconfig"

cd "$SRC"
./mach --no-interactive bootstrap --application-choice=browser
./mach build
./mach package

TARBALL="$(ls -t obj-iuk-browser/dist/*.tar.* | head -1)"
echo ">> Built: $TARBALL"
[ "${SKIP_PACKAGE:-0}" = 1 ] && exit 0
cd "$REPO"
SOURCE_BUILD=1 FIREFOX_TARBALL="$SRC/$TARBALL" packaging/build-bundle.sh linux "$FFVER"
