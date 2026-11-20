# TODO

## Planned next (deferred on purpose)

- [ ] **QR pairing**: show a QR code on the first device containing server URL + user name + key (shown only locally, never sent anywhere); scan it on the second device instead of retyping the secret key.
- [ ] **Argon2id** key derivation: replace PBKDF2 (600k iterations) with Argon2id via a bundled WASM build. Needs a versioned KDF header in the vault and in the synced blob so existing data can be migrated.

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
