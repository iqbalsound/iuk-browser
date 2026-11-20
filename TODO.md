# TODO

## Done in 1.1.0

- [x] **QR pairing** (show on one device, scan on the other; camera, image or pasted code)
- [x] **Argon2id** key derivation with automatic PBKDF2 migration

## Planned next

- [ ] Run Argon2id in a Web Worker so the browser UI never pauses while deriving the key
- [ ] Time-limited, one-use pairing tokens (so a leaked QR screenshot cannot be reused after pairing)

## First source build: verify

- [ ] `build/build-source.sh` completes on a clean Linux machine and produces DEB + RPM
- [ ] Window, taskbar, alt-tab and *minimized window* icons show the IUK logo (Wayland and X11)
- [ ] About dialog, `about:` pages and the new-window/private-window launcher actions show IUK Browser branding
- [ ] The bundled add-on installs unsigned (`about:addons`), and `about:policies` shows no errors
- [ ] Profile location and `MOZ_APP_REMOTINGNAME` behave as expected (no clash with a normal Firefox)
- [ ] Windows: build with MozillaBuild (`build/mozconfig.windows`), run `packaging/build-bundle.sh windows` with `FIREFOX_ZIP`

## Later

- [ ] Rename the internal binary from `firefox` to `iuk-browser` (needs `MOZ_APP_NAME`, touches many build files)
- [ ] apt/dnf repository and a Windows auto-update channel (updates are currently disabled by policy)
- [ ] Windows CI for the source build; code-sign the installer
- [ ] Second-factor option for the relay; tags and folder-level conflict handling for bookmarks
- [ ] Clear the clipboard automatically after copying a password
- [ ] Translations of the extension UI
