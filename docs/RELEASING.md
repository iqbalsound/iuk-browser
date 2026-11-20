# Releasing IUK Browser

The release pipeline is `.github/workflows/release.yml`. It builds the **extension**, **DEB**, **RPM** and the **Windows installer (`-setup.exe`) and portable zip**, writes `SHA256SUMS`, and creates a **draft** GitHub Release for you to review and publish.

## Cut a release

1. Bump the version in **both** `extension/manifest.json` and `package.json`, and add a `## [x.y.z]` section to `CHANGELOG.md` (it becomes the release notes). The workflow fails early if these disagree with the tag.
2. Commit and push over SSH: `git push origin main`.
3. Tag and push the tag: `git tag v1.1.0 && git push origin v1.1.0`.
4. Watch **Actions → Release**. When it is green, open **Releases**, check the draft and press **Publish**.

You can also run it by hand: **Actions → Release → Run workflow** (choose the mode; leave *tag* empty to just build artifacts).

## Two build modes

| | `bundle` (default) | `source` |
|---|---|---|
| What | Official Firefox ESR binaries + IUK layer and icons | Gecko compiled from source with IUK branding |
| Time | minutes | hours (Linux), experimental (Windows) |
| Files attached to the release | extension only | extension + DEB + RPM + setup.exe + portable zip |
| Why | Mozilla's trademark policy forbids publishing Mozilla-branded modified binaries; bundle output stays in the run's private artifacts for personal use | The unofficial-branding build contains no Mozilla marks and may be redistributed |

Set the default for tag pushes in **Settings → Secrets and variables → Actions → Variables**: `IUK_BUILD_MODE` = `bundle` or `source`.

**Want the DEB, RPM and EXE on the release page in bundle mode?** Allowed for a **private** repository or personal use: tick *attach_binaries* when running the workflow by hand, or set the variable `IUK_ATTACH_BUNDLES` = `true` for tag pushes. The release notes then say the packages are Mozilla-branded and not for public redistribution. For a **public** repository use `source` mode instead.

## Runners for source builds

Gecko needs about 40 GB of disk and several hours. Standard GitHub-hosted runners have a 6 hour job limit and little disk, so a source build may fail there. Create a larger runner or a self-hosted runner and set the repository variables `LINUX_RUNNER` and `WINDOWS_RUNNER` to its label. The Windows source build uses MozillaBuild and is experimental; if it cannot succeed, build Windows locally ([BUILD-FROM-SOURCE.md](BUILD-FROM-SOURCE.md)) and attach the installer to the draft by hand.

## What the jobs do

`meta` (validates tag/version/changelog, picks the Firefox ESR tag) → `test` (unit tests, lint, builds `iuk-browser-<v>-extension.zip` and `.xpi`) → `linux` (DEB + RPM) and `overlay` → `windows-build` → `windows` (installer + zip) → `release` (draft).

## Install notes

- DEB: `sudo apt install ./iuk-browser_1.1.0-1_amd64.deb` · RPM: `sudo dnf install ./iuk-browser-1.1.0-1.x86_64.rpm`
- Windows: run `iuk-browser-1.1.0-setup.exe`, or unzip the portable zip. The installer is unsigned, so SmartScreen will warn until it builds reputation or you sign it.
- Verify downloads: `sha256sum -c SHA256SUMS`.
- Upgrading from 1.0: install, open the browser, unlock the vault on every device. Each vault migrates to Argon2id at its first unlock; unlock all devices to finish.
