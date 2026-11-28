#!/usr/bin/env bash
# Usage (on macOS):  packaging/macos/build-macos.sh <version>
# Freezes "IUK Browser.app", signs it with a Developer ID certificate and notarizes the .dmg when the secrets exist.
#   APPLE_CERT_P12_BASE64   base64 of the "Developer ID Application" certificate (.p12)
#   APPLE_CERT_PASSWORD     its password
#   APPLE_ID, APPLE_TEAM_ID, APPLE_APP_PASSWORD   for notarization (an app-specific password)
# Without them the .dmg is built UNSIGNED (Gatekeeper will warn; right-click > Open).
# NOTE: this script has not been run by its author (no macOS machine); treat it as a starting point.
set -euo pipefail
VERSION="${1:?version}"
python3 -m PyInstaller packaging/iuk-browser.spec --noconfirm
APP="dist/IUK Browser.app"
[ -d "$APP" ] || { echo "PyInstaller did not produce $APP"; exit 1; }

IDENTITY=""
if [ -n "${APPLE_CERT_P12_BASE64:-}" ]; then
  KC="${RUNNER_TEMP:-/tmp}/iuk-build.keychain-db"; KCPASS="$(uuidgen)"
  echo "$APPLE_CERT_P12_BASE64" | base64 -d > "${RUNNER_TEMP:-/tmp}/iuk-cert.p12"
  security create-keychain -p "$KCPASS" "$KC"
  security set-keychain-settings -lut 21600 "$KC"
  security unlock-keychain -p "$KCPASS" "$KC"
  security import "${RUNNER_TEMP:-/tmp}/iuk-cert.p12" -k "$KC" -P "${APPLE_CERT_PASSWORD:-}" -T /usr/bin/codesign
  security set-key-partition-list -S apple-tool:,apple: -s -k "$KCPASS" "$KC" >/dev/null
  security list-keychains -d user -s "$KC" login.keychain-db
  rm -f "${RUNNER_TEMP:-/tmp}/iuk-cert.p12"
  IDENTITY="$(security find-identity -v -p codesigning "$KC" | awk -F'"' '/Developer ID Application/{print $2; exit}')"
fi

if [ -n "$IDENTITY" ]; then
  # sign every Mach-O inside the bundle first (deepest files first), then the bundle itself
  find "$APP" -type f -print0 | while IFS= read -r -d '' f; do
    if file "$f" | grep -q "Mach-O"; then
      codesign --force --options runtime --timestamp --entitlements packaging/macos/entitlements.plist --sign "$IDENTITY" "$f"
    fi
  done
  codesign --force --options runtime --timestamp --entitlements packaging/macos/entitlements.plist --sign "$IDENTITY" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
else
  echo "WARNING: no Developer ID certificate configured: the app and dmg are NOT signed"
fi

STAGE=dist/dmg; rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"; ln -s /Applications "$STAGE/Applications"
DMG="dist/iuk-browser-$VERSION-macos-$(uname -m).dmg"
hdiutil create -volname "IUK Browser" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
[ -n "$IDENTITY" ] && codesign --force --timestamp --sign "$IDENTITY" "$DMG"
if [ -n "$IDENTITY" ] && [ -n "${APPLE_ID:-}" ]; then
  xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "${APPLE_TEAM_ID:?}" --password "${APPLE_APP_PASSWORD:?}" --wait
  xcrun stapler staple "$DMG"
fi
ls -lh dist/*.dmg
