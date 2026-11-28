# Releasing IUK Browser

Pipeline: **tag** → `release.yml` builds everything and drafts a GitHub Release → you **publish** it →
`publish-repos.yml` publishes the apt/dnf repositories and the signed update manifest.

## One-time setup

### 1. Push the repository over SSH
```bash
git init -b main && git add -A && git commit -m "IUK Browser 2.1.0"
git remote add origin git@github.com:iqbalsound/iuk-browser.git      # your account/repo
git push -u origin main
```
Settings → Actions → General → Workflow permissions: **Read and write**.

### 2. GitHub Pages (hosts the apt/dnf repos and the update manifests)
Settings → Pages → Source: **Deploy from a branch**, branch `gh-pages`, folder `/ (root)`. The branch is created by the first publish.
Your site will be `https://<your-user>.github.io/<repo>/`. Put that into `UPDATE_BASE_URL` (+ `/update`) in
`src/iuk_browser/core/update_keys.py`.

### 3. Signing keys (secrets: Settings → Secrets and variables → Actions)

| Secret | What | How |
|---|---|---|
| `GPG_PRIVATE_KEY` | signs the apt/dnf metadata and the RPM | `gpg --quick-generate-key "IUK Browser Releases <you@example.com>" ed25519 sign 0` then `gpg --armor --export-secret-keys <KEYID> \| base64 -w0` |
| `GPG_PASSPHRASE` | its passphrase | chosen at generation |
| `UPDATE_SIGNING_KEY` | signs the in-app update manifest | `python packaging/tools/gen_update_key.py`: private line → secret, **public line → `UPDATE_PUBLIC_KEYS` in `update_keys.py`** (commit that) |
| `WINDOWS_CERT_PFX_BASE64`, `WINDOWS_CERT_PASSWORD` | Authenticode certificate for `iuk-browser.exe` and the installer | `base64 -w0 cert.pfx` (an OV or EV code-signing certificate) |

| `APPLE_CERT_P12_BASE64`, `APPLE_CERT_PASSWORD`, `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` | macOS Developer ID signing and notarization (optional, experimental) | Apple Developer account; the app-specific password is created at appleid.apple.com |

Back up both private keys. Without the update key, installed copies cannot trust new updates; without the GPG key, apt/dnf
users must re-import a new key. Every secret is optional, but without them the output is unsigned (the workflows warn).
Azure Trusted Signing or SignPath can replace the PFX step in `packaging/windows/sign.ps1`.

## Every release
1. Bump the version in `pyproject.toml` **and** `src/iuk_browser/__init__.py`; add a `## [x.y.z]` section to `CHANGELOG.md`.
2. `git commit -am "Release x.y.z" && git push origin main` (CI must be green).
3. Tag and push the tag: `git tag v2.1.0 && git push origin v2.1.0`. The workflow refuses a tag that disagrees with the files.
4. Watch **Actions → Release**. It produces `iuk-browser_<v>-1_amd64.deb`, `iuk-browser-<v>-1.x86_64.rpm`, `iuk-browser-<v>-x86_64.AppImage`,
   `iuk-browser-<v>-setup.exe`, `iuk-browser-<v>-win64-portable.zip`, `SHA256SUMS`, a **draft** release, and (if the experimental macOS job
   succeeds) `iuk-browser-<v>-macos-arm64.dmg`. The macOS job may fail without blocking the release.
5. Open **Releases**, check the draft, press **Publish release**. `publish-repos.yml` then updates `gh-pages`.
   (Pre-release versions such as `2.2.0-beta.1` go to the `beta` update channel.)

Re-run a failed publish: Actions → *Publish repositories and update channel* → Run workflow → tag.

## Installing from the repositories
```bash
# Debian / Ubuntu
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://<user>.github.io/<repo>/iuk-browser.gpg | sudo tee /etc/apt/keyrings/iuk-browser.gpg >/dev/null
curl -fsSL https://<user>.github.io/<repo>/apt/iuk-browser.sources | sudo tee /etc/apt/sources.list.d/iuk-browser.sources >/dev/null
sudo apt update && sudo apt install iuk-browser

# Fedora / RHEL
sudo curl -fsSL -o /etc/yum.repos.d/iuk-browser.repo https://<user>.github.io/<repo>/rpm/iuk-browser.repo
sudo dnf install iuk-browser
```
AppImage: `chmod +x iuk-browser-*.AppImage && ./iuk-browser-*.AppImage`.
Windows: run the installer; it installs per user and the app updates itself (Settings → Updates; checks daily).

## Build locally
```bash
pip install -e ".[dev]"
python -m PyInstaller packaging/iuk-browser.spec --noconfirm     # dist/iuk-browser/iuk-browser
packaging/build-linux.sh 2.1.0                                   # needs nfpm; writes dist/pkg/*.deb, *.rpm
powershell -File packaging\build-windows.ps1 -Version 2.1.0      # on Windows; needs NSIS (choco install nsis)
```
Set `QT_QPA_PLATFORM=offscreen` when freezing on a machine without a display.

## Troubleshooting
| Symptom | Cause / fix |
|---|---|
| "CHANGELOG.md has no section for X" or version mismatch | the three version places disagree: fix and re-tag (`git tag -d v2.1.0 && git push origin :refs/tags/v2.1.0`) |
| apt says NO_PUBKEY / "not signed" | the key file in `/etc/apt/keyrings/` is missing or stale; re-download `iuk-browser.gpg` |
| dnf: "repomd.xml GPG signature verification error" | re-import `iuk-browser.asc`; check `GPG_PRIVATE_KEY` is the **armored** key, base64-encoded |
| Windows SmartScreen warning | the installer is unsigned or the certificate is new (OV certificates build reputation over time; EV is immediate) |
| The app does not offer updates | `UPDATE_PUBLIC_KEYS` is empty, `UPDATE_BASE_URL` is wrong, or `UPDATE_SIGNING_KEY` was missing when the release was published |
