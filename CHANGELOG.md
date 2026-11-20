# Changelog

## [1.1.0] - 2026-11-20

### Added
- **QR pairing.** Show a QR code on a set-up device and scan it on a new one (camera, image file, or pasted code) to move user name, secret key and server address without typing the key. The key must be re-entered to reveal the QR, the QR hides itself after 90 seconds, and the new device asks for confirmation before joining. Open it from the toolbar (**QR**), the setup screen, or Settings.
- **Argon2id key derivation** (64 MiB, 3 passes, 1 lane; verified against the reference libargon2) replaces PBKDF2 for new vaults. The KDF version is stored with the vault and inside each synced document (`argon2id-v2`).
- **Automatic migration.** Existing PBKDF2 vaults upgrade the next time they are unlocked: the local vault and the server copy are merged, re-encrypted with the Argon2id key, uploaded to the new location, and only then is the local state switched in a single write. The old server copy is deleted. If the server is unreachable the vault keeps working and retries at the next unlock. Upgrade every device; a device still on 1.0 syncs separately.
- Relay server: authenticated `DELETE /v1/blob`.
- Release workflow that builds the extension, DEB, RPM and the Windows installer + portable zip, and drafts a GitHub Release (`.github/workflows/release.yml`).
- Vendored libraries (no network at runtime): hash-wasm 4.12.0, qrcode-generator 2.0.4, jsQR 1.4.0 (`extension/vendor/`).

### Changed
- Extension content security policy allows WebAssembly (`'wasm-unsafe-eval'`) for Argon2id.
- Setting up a device that already has a vault now asks you to use "Forget this device" first instead of overwriting it.

## [1.0.0]

Initial release: IUK Browser branding and source build, encrypted bookmark and password sync (PBKDF2), password manager, themes, color invert, DEB / RPM / Windows packaging.
