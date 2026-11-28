# Changelog

## [2.2.0] - 2026-11-25

### Security
- **One-time pairing codes.** The pairing QR no longer contains your secret key. It carries a random pairing id and a random
  one-time key; the account details are uploaded to the relay encrypted with that one-time key, can be fetched exactly once,
  live in relay memory only and expire after 2 minutes. The showing device notices when the other device has paired (and
  withdraws the QR); closing the dialog withdraws an unused QR. A screenshot of a used or expired QR is useless. Without a sync
  server the dialog falls back to the previous direct code (`IUKB1:`), which stays compatible with the 1.x extension.
- **Auto-lock** after N minutes of inactivity (default 15, 0 = never): locks the vault and wipes the copied secret from the
  clipboard. It waits while a dialog such as the password manager is open.
- **Fixed:** locking the vault while a sync was in flight could leave decrypted logins in memory. A sync now aborts
  ("The vault was locked during sync") and drops everything.

### Added
- **Tracker and ad blocking**: an Adblock-Plus-syntax filter engine (domain rules, exceptions, `$third-party`, resource types),
  a conservative starter list, your own filter lists (Settings > Security), a per-site "Allow trackers on this site" switch and a
  "N blocked" counter. Page navigations are never blocked; rules that cannot be honored exactly are skipped, not approximated.
- **Site permission manager**: location, camera, microphone, notifications, ... are remembered per site (not in private
  windows); allow, block or forget each one, or all of them.
- **Cancel** for the long key derivation in the setup, unlock and pairing dialogs, with a progress bar. Cancelling stops the
  operation before anything is stored.
- **Set as default browser** (Linux: `xdg-settings`; Windows: opens Settings). The Windows installer now registers IUK Browser
  as a selectable default browser (HTTP/HTTPS and HTML file associations).
- **AppImage** for distributions without apt or dnf.
- **macOS**: PyInstaller bundle, `.dmg`, Developer ID signing and notarization scripts and an (allowed-to-fail, experimental)
  CI job. Not run by the author: no macOS machine.
- **Translation review tooling** (`tools/review_translations.py`): export a CSV per language for a native speaker, import their
  corrections with placeholder validation. 38 new strings translated in all six languages.
- Relay: `PUT|GET|DELETE /v1/pair/<id>` and `GET /v1/pair/<id>/status` (see docs/SERVER.md).

### Notes
- An application-wide Python event filter crashes Qt WebEngine, so activity tracking uses per-widget filters.
- Not done: Flatpak (needs a runtime build environment), native-speaker review itself, a macOS run.

## [2.1.0] - 2026-11-22

IUK Browser is now a **Qt WebEngine (PySide6)** application. It replaces the Gecko/Firefox-extension edition (1.x) and
keeps every feature of 1.1.0: encrypted sync of bookmarks and passwords, password manager, QR pairing, Argon2id, themes
and color invert, DEB / RPM / Windows packages.

### Added
- **Complete browser**: tabs, address bar with search, history, downloads, find in page, zoom, full screen, view source,
  print to PDF, developer tools, private windows (off-the-record profile), permission prompts, HTTP authentication,
  session restore, single instance (links open in the running browser), web-page dark-mode request.
- **Bookmark tags** (conflict-free per-tag merge) and **folders with conflict handling**: field-level last-write-wins,
  items in a folder deleted elsewhere are shown under "Recovered items", concurrent folder moves can never form a cycle.
  Netscape-HTML import and export.
- **Second factor for the sync relay** (TOTP + recovery codes, session tokens, replay and brute-force protection).
- **Automatic clipboard clearing** after copying a password or user name, and clipboard-history exclusion hints.
- **Translations**: Urdu, Arabic, French, Spanish, German, Simplified Chinese (RTL layouts for Urdu and Arabic).
- **Signed update channel**: Ed25519-signed manifests; the Windows build downloads, verifies (signature and SHA-256)
  and installs updates silently; Linux updates through apt/dnf.
- **apt and dnf repositories** (signed, published to GitHub Pages).
- **Windows installer** is per-user (no administrator prompt) and is Authenticode-signed when a certificate is configured.
- Release automation: `release.yml` builds DEB, RPM, Windows installer and portable zip and drafts a GitHub Release;
  `publish-repos.yml` publishes the repositories and the update manifest when you publish it.
- The relay server is now a single stdlib-only Python file (`server/iuk_relay.py`) and stays wire-compatible with the
  1.x extension for the blob protocol.

### Changed
- The synced document is **format v2** (bookmark ids, folder ids, per-field timestamps, tags). Existing v1 data written by
  the 1.x extension is read and converted automatically the first time a 2.x device syncs, and is rewritten as v2.
  After that, 1.x extension devices refuse to sync ("Unsupported sync data version") instead of corrupting data.
  Upgrade every device. Accounts, keys, KDF and the encrypted container format are unchanged.
- The internal binary, process name, window class and desktop entry are all `iuk-browser`.

### Fixed
- Re-adding a login after deleting it no longer fails.

## [1.1.0]

QR pairing and Argon2id for the Firefox-extension edition. See the `v1.1.0` tag.
