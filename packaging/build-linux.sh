#!/usr/bin/env bash
# Usage: packaging/build-linux.sh <version>      (run from the repository root)
# Freezes the app with PyInstaller (unless dist/iuk-browser exists) and packages DEB + RPM with nfpm.
# Optional RPM signing: export NFPM_SIGNING_KEY_FILE=<armored private key> and NFPM_PASSPHRASE=<passphrase>.
set -euo pipefail
VERSION="${1:?version}"
[ -d dist/iuk-browser ] || QT_QPA_PLATFORM=offscreen python3 -m PyInstaller packaging/iuk-browser.spec --noconfirm
test -x dist/iuk-browser/iuk-browser
export VERSION MAINTAINER="${MAINTAINER:-IUK Browser <noreply@example.com>}" GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-iqbalsound/iuk-browser}"
CFG=packaging/linux/nfpm.yaml
if [ -z "${NFPM_SIGNING_KEY_FILE:-}" ]; then            # unsigned rpm: drop the signature block
  sed '/signature:/,+1d' "$CFG" > dist/nfpm-unsigned.yaml; CFG=dist/nfpm-unsigned.yaml
fi
mkdir -p dist/pkg
nfpm package -f "$CFG" -p deb -t dist/pkg/
nfpm package -f "$CFG" -p rpm -t dist/pkg/
ls -lh dist/pkg
