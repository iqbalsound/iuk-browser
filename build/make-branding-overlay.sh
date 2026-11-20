#!/usr/bin/env bash
# Builds dist/branding-overlay.tar.gz: browser/branding/iuk-browser + the patched browser/confvars.sh for an ESR tag.
# Needs only a sparse clone (a few MB), so branding can be done on Linux and unpacked onto a Windows source tree
# (cairosvg needs Cairo, which is awkward on Windows).   tar -xzf dist/branding-overlay.tar.gz -C <firefox-src>
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"; WORK="${WORK:-$REPO/.build}"; SRC="$WORK/branding-src"
REF="$(build/resolve-esr-tag.sh)"; echo ">> overlay for $REF"
rm -rf "$SRC"; mkdir -p "$WORK" dist
git clone --quiet --depth 1 --branch "$REF" --filter=blob:none --sparse "${UPSTREAM:-https://github.com/mozilla-firefox/firefox}" "$SRC"
git -C "$SRC" sparse-checkout set --no-cone /browser/branding/ /browser/confvars.sh
python3 -m venv "$WORK/venv"; "$WORK/venv/bin/pip" install -q -r branding/requirements.txt
"$WORK/venv/bin/python" branding/apply_to_source.py "$SRC"
tar -czf dist/branding-overlay.tar.gz -C "$SRC" browser/branding/iuk-browser browser/confvars.sh
echo "$REF" > dist/firefox-ref.txt
ls -lh dist/branding-overlay.tar.gz
