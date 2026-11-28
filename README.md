# IUK Browser 2.2

A web browser built on **Qt WebEngine (PySide6)** with **end-to-end encrypted sync** of bookmarks and passwords.

- **Browser**: tabs, address bar with search, history, downloads, find in page, zoom, view source, print to PDF, developer tools,
  private windows, session restore, permission prompts, single instance.
- **Sync** between devices that share the same *user name + secret connectivity key*. Argon2id key derivation, AES-256-GCM,
  a zero-knowledge relay that only ever stores ciphertext, last-write-wins merge **per field**.
- **Password manager**: encrypted vault, autofill (explicit action, isolated from page scripts), save/update prompt, generator,
  CSV import/export, **clipboard cleared automatically** after copying.
- **QR pairing with one-time codes**: the QR never contains your key, works once and expires after 2 minutes; the other device
  scans it (camera, image or pasted code) and the showing device sees that it was used.
- **Bookmarks with tags and folders**; conflicts between devices are resolved without losing data (see below).
- **Second factor for the sync relay** (TOTP authenticator app + recovery codes), optional.
- **Tracker and ad blocking** (Adblock-Plus-syntax engine, starter list, your own lists, per-site allow) and a **site permission
  manager**.
- **Auto-lock** after inactivity and automatic **clipboard clearing**.
- **Themes** (7 presets + custom colors) and **color invert** (global or per site, brightness / contrast / sepia).
- **Languages**: English, Urdu, Arabic, French, Spanish, German, Simplified Chinese (right-to-left layouts for Urdu and Arabic).
- **Packages**: DEB, RPM (signed apt/dnf repositories), AppImage, Windows installer (per-user, code-signed, **auto-updating**,
  selectable as default browser) and portable zip; an experimental macOS `.dmg`.

Everything is checked by automated tests; see [docs/FEATURES.md](docs/FEATURES.md) for the evidence and for what is still manual.

## Run from source
```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m iuk_browser                                # or: iuk-browser [--private] [--data-dir DIR] [URL ...]
pytest -q
```

## Install
| Platform | How |
|---|---|
| Debian / Ubuntu | `sudo apt install ./iuk-browser_<v>-1_amd64.deb`, or use the apt repository ([docs/RELEASING.md](docs/RELEASING.md)) |
| Fedora / RHEL | `sudo dnf install ./iuk-browser-<v>-1.x86_64.rpm`, or the dnf repository |
| Any Linux | `chmod +x iuk-browser-<v>-x86_64.AppImage && ./iuk-browser-<v>-x86_64.AppImage` |
| Windows | run `iuk-browser-<v>-setup.exe` (no administrator rights needed); the app then updates itself |
| macOS | experimental: `.dmg` from the release (signed and notarized only if you configured Apple credentials) |

The program, process, window class and desktop entry are all named `iuk-browser`.

## Set up sync
1. Run the relay on a server you control ([docs/SERVER.md](docs/SERVER.md)): `python3 server/iuk_relay.py` behind HTTPS.
2. Menu → *Passwords* → *Set up passwords and sync…*: user name, secret key (use **Generate key**), server URL.
3. On the first device choose *Pair another device (QR)…* (retype your key); on the second device choose *Scan pairing QR…* in the setup
   dialog. The QR works once and expires after 2 minutes.
4. Optional: Settings → Sync → *Second factor for the sync relay…*.

**Your key cannot be recovered.** Write it down. A mistyped key on a *new* device does not fail: it simply is a different, empty account.

## How conflicts are resolved
| Situation | Result |
|---|---|
| Device A renames a bookmark, device B moves it and adds a tag | all three changes survive (merge is per field; tags are independent) |
| B adds a bookmark into a folder that A deleted | the bookmark appears under **Recovered items**; nothing is lost |
| A moves folder One into Two while B moves Two into One | no cycle: one of them is shown under *Other bookmarks* |
| Both devices changed the same field | the later change wins; ties break deterministically so every device converges |

Randomized three-device tests check that any sync order ends in the same state.

## Security model
- The AES key is derived from user name + secret with Argon2id (64 MiB, 3 passes) and never leaves the device; the relay token
  is an independent half of the same derivation, so knowing it reveals nothing about the key.
- The relay stores one encrypted blob per account. With the optional second factor, a stolen token alone cannot even download it.
- Web pages cannot see the autofill code or the Python bridge (isolated script world); the page address used for matching comes
  from Qt, not from page script; autofill only runs on your explicit action and only in the top frame.
- With a sync server the pairing QR is **one-time**: it holds a random id and a one-time key, not your account key; the details sit
  encrypted on the relay (memory only) for 2 minutes and can be fetched once. Retyping your key is still required to show it.
  Without a server the QR falls back to a direct code that does contain the key (hides after 90 s).
- The vault locks itself after inactivity (default 15 min) and a lock during a sync cannot leave decrypted data behind.
- Updates are Ed25519-signed and checked against a SHA-256 before being run; apt/dnf metadata is GPG-signed.

## Repository layout
| Path | |
|---|---|
| `src/iuk_browser/core/` | crypto, merge engine, bookmark store, vault/sync, relay client, updater (no Qt) |
| `src/iuk_browser/ui/` | main window, dialogs, WebEngine glue and injected scripts |
| `server/` | the relay (`iuk_relay.py`, Dockerfile, systemd unit) |
| `packaging/` | PyInstaller spec, nfpm (DEB/RPM), NSIS installer, signing, apt/dnf repository and update-manifest tools |
| `branding/` | logo artwork and the icon generator |
| `tools/`, `src/iuk_browser/i18n/` | translations ([docs/TRANSLATING.md](docs/TRANSLATING.md)) |
| `.github/workflows/` | CI, release, repository publishing |
| `tests/` | 135 tests, including real WebEngine pages and a real relay |

## Releasing
`git tag v2.1.0 && git push origin v2.1.0` builds and signs everything and drafts a release; publishing it updates the apt/dnf
repositories and the update channel. Full guide: [docs/RELEASING.md](docs/RELEASING.md).

## Known limitations
- Camera scanning, permission prompts, full-screen video, the Windows installer/updater running on a real Windows machine, and
  signing with a real certificate were **not** exercised in the authoring environment (no camera, Windows host or certificate).
  The image and pasted-code paths, the signature and checksum logic, the installer compile, and the Linux packages were.
- The six translations are unreviewed by native speakers.
- The blocker understands the common subset of Adblock Plus syntax (wildcard, regex and `$domain=` rules are skipped); the starter
  list is small. No extensions API or sync of browsing history yet ([TODO.md](TODO.md)).
- The macOS build and notarization were written but **not run** (no macOS machine); Flatpak is not provided.
- The bundle includes Chromium, so packages are large (about 260 MB).

## License
MIT for this repository. Qt and Chromium are covered by their own licenses (LGPL / BSD and others).
