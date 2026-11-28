# Feature check: everything from 1.1.0, plus the 2.1.0 additions

"Evidence" is the automated test that exercises the feature (run `pytest`). Items marked **manual** have no automated
test (they need a real desktop, camera, Windows machine or certificate).

## Carried over from 1.1.0

| Feature | In 2.1.0 | Evidence |
|---|---|---|
| Argon2id key derivation (64 MiB, 3 passes), byte-compatible with the extension | yes | `test_crypto_interop`: known-answer vector from the extension and from libargon2 |
| AES-256-GCM container `v1.iv.ct`, wrong key / tampering rejected | yes | `test_crypto_interop` (decrypts a blob written by the extension) |
| Zero-knowledge relay, `If-Match` optimistic concurrency, DELETE, isolation between accounts | yes | `test_relay` |
| Two-device sync of bookmarks and passwords, deletes propagate, ciphertext only on the server | yes | `test_account_sync` |
| Password manager: vault encrypted at rest, unlock/lock, CSV import/export, generator | yes | `test_account_sync`, `test_dialogs` |
| Autofill (explicit action, top frame only, isolated from page scripts) and save prompt | yes | `test_web`, `test_app_smoke` (real WebEngine) |
| QR pairing: show, scan from image / camera / pasted code, same `IUKB1:` code as the extension | yes | `test_dialogs`, `test_crypto_interop` (code identical to the extension's); camera: **manual** |
| Themes (7 presets + custom) | yes | `test_core_misc`, `test_app_smoke` |
| Color invert (global / per site, media kept natural, brightness / contrast / sepia), live update | yes | `test_web`, `test_app_smoke` |
| Reads data written by the 1.x extension | yes | `test_account_sync::test_reads_data_written_by_the_firefox_extension...` |
| DEB, RPM, Windows installer | yes | DEB installed and run on Ubuntu 24.04, RPM built; Windows installer compiled; running it on Windows: **manual** |

## New in 2.1.0 (your list)

| Item | Result | Evidence |
|---|---|---|
| Internal binary named `iuk-browser` | native to the Qt edition: binary, process, desktop file, window class | frozen binary run; DEB installed, `iuk-browser --version` |
| apt / dnf repositories | signed repos built by `packaging/repo/build-site.sh` | real `apt-get update` accepts it; a tampered package list is rejected; RPM repo metadata signature verified |
| Windows auto-update channel | Ed25519-signed manifests, SHA-256 verified silent installer | `test_core_misc` (forged, tampered, wrong channel, unsigned, bad checksum, non-HTTPS); running an update on Windows: **manual** |
| Windows CI + code signing | `release.yml` windows job, `sign.ps1` (signtool) | workflow validated with actionlint; installer compiled; signing with a real certificate: **manual** |
| Second factor for the relay | TOTP + recovery codes + sessions | `test_relay`, `test_account_sync`, `test_dialogs` (RFC 6238 vectors, replay, lockout, expiry) |
| Bookmark tags | conflict-free per-tag merge | `test_bookmarks_merge` |
| Folder-level conflict handling | per-field LWW, "Recovered items", cycle breaking | `test_bookmarks_merge` incl. 15 randomized three-replica convergence runs |
| Clipboard auto-clear | clears after N seconds, never someone else's text | `test_app_smoke` |
| Translations | ur, ar, fr, es, de, zh_CN (RTL for ar, ur) | `test_core_misc` (complete, placeholders match) |

## Browser features

Tabs, navigation, address bar, history, find, zoom, view source, print to PDF, developer tools, downloads, private windows,
session restore, single instance: `test_app_smoke`, `test_browser_features`.
Permission prompts, HTTP-auth dialog, full-screen video, and the look of the UI on a real desktop: **manual**.


## Added in 2.2.0

| Item | Evidence |
|---|---|
| One-time pairing codes (never contain the key; once; 2 min; owner status; withdraw on close; fallback to direct code) | `test_relay` (once, expiry, ownership, limits, 2FA gate, memory only), `test_account_sync`, `test_dialogs` (scan, replay of a used QR, withdrawal) |
| Cancel + progress for key derivation, nothing stored on cancel | `test_dialogs::test_setup_and_unlock_can_be_cancelled...` |
| Auto-lock (inactivity, activity postpones, clipboard wiped, waits for modal dialogs, "Never") | `test_app_smoke` |
| Lock during sync leaves no decrypted logins | `test_account_sync::test_locking_during_a_sync...` |
| Tracker / ad blocking (engine, 60 000-rule speed, real third-party image blocked, own resources and navigation untouched, menu toggles, per-site allow) | `test_blocker` (real WebEngine) |
| Site permission manager (remembered, allow/block/reset/reset all, private windows not persisted) | `test_browser_features` |
| Default browser action | `test_app_smoke` (xdg-settings / Windows Settings, mocked); registry entries compiled into the installer; Windows picking it: **manual** |
| AppImage | built, run with `--appimage-extract-and-run`: loads a page, history recorded |
| Translation review round trip | `test_core_misc` |
| macOS `.app` / `.dmg` / notarization | scripts written, **not run** |
