#!/usr/bin/env bash
# Prints the Firefox ESR release tag to build: $FIREFOX_REF if set, otherwise the newest *esr*_RELEASE tag.
set -euo pipefail
UPSTREAM="${UPSTREAM:-https://github.com/mozilla-firefox/firefox}"
if [ -n "${FIREFOX_REF:-}" ]; then echo "$FIREFOX_REF"; exit 0; fi
tag="$(git ls-remote --tags "$UPSTREAM" 'FIREFOX_*esr*_RELEASE' | awk '{print $2}' | sed 's#refs/tags/##' | sort -V | tail -1)"
[ -n "$tag" ] || { echo "Could not determine an ESR tag; set FIREFOX_REF" >&2; exit 1; }
echo "$tag"
