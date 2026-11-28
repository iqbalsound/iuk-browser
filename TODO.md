# TODO

## Done in 2.2.0
- [x] Key derivation shows progress and can be cancelled before anything is stored
- [x] One-use, short-lived pairing codes (the QR no longer carries the account key)
- [x] Auto-lock after inactivity
- [x] Windows: selectable as a default browser (+ "Set as default browser" on Linux and Windows)
- [x] AppImage
- [x] Tracker / ad blocking (filter engine, starter list, per-site allow, your own lists)
- [x] Per-site permission manager
- [x] Tooling for native-speaker translation review
- [~] macOS build + notarization: scripts and an experimental CI job written, **not run** (no macOS machine)

## Still open
- [ ] Native-speaker review of the six translations (use `tools/review_translations.py`, see docs/TRANSLATING.md)
- [ ] Run the macOS job once with Apple credentials and fix what it finds
- [ ] Flatpak (Flathub) packaging
- [ ] Auto-download of filter lists (EasyList / EasyPrivacy) with signatures or pinned hashes
- [ ] Sync of browsing history and open tabs (encrypted, opt-in)
- [ ] Extensions API (WebExtensions are not available in Qt WebEngine)
- [ ] Hardware-key (WebAuthn / FIDO2) second factor for the relay
- [ ] Per-site zoom and a settings page for permission defaults
