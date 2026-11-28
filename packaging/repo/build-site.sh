#!/usr/bin/env bash
# Builds the signed apt + dnf repositories and the update channel into a static site (served by GitHub Pages).
#
#   packaging/repo/build-site.sh <dir with .deb/.rpm> <site dir>
#
# Environment:
#   SITE_URL         public base URL, e.g. https://iqbalsound.github.io/iuk-browser          (required)
#   GPG_PRIVATE_KEY  base64 of the ARMORED private signing key                                (required)
#   GPG_PASSPHRASE   its passphrase, if any
#   RPM_SIGNED=1     the .rpm files themselves are signed (nfpm signature): sets gpgcheck=1 in the .repo file
#
# The site directory may already contain older releases (the gh-pages checkout): packages accumulate in the
# pool and the metadata is regenerated over all of them.
set -euo pipefail
PKG="${1:?directory with .deb/.rpm}"; SITE="${2:?site directory}"
: "${SITE_URL:?}"; : "${GPG_PRIVATE_KEY:?}"
SITE_URL="${SITE_URL%/}"
export GNUPGHOME; GNUPGHOME="$(mktemp -d)"; chmod 700 "$GNUPGHOME"
trap 'gpgconf --kill gpg-agent >/dev/null 2>&1 || true; rm -rf "$GNUPGHOME"' EXIT
echo "$GPG_PRIVATE_KEY" | base64 -d | gpg --batch --quiet --import
KEYID="$(gpg --list-secret-keys --with-colons | awk -F: '/^fpr/{print $10; exit}')"
sign() { gpg --batch --yes --quiet --pinentry-mode loopback --passphrase "${GPG_PASSPHRASE:-}" -u "$KEYID" "$@"; }
mkdir -p "$SITE"

# ---------------------------------------------------------------- apt
APT="$SITE/apt"; POOL="$APT/pool/main/i/iuk-browser"; DIST="$APT/dists/stable"
mkdir -p "$POOL" "$DIST/main/binary-amd64"
cp -f "$PKG"/*.deb "$POOL"/
( cd "$APT"
  apt-ftparchive packages pool > dists/stable/main/binary-amd64/Packages
  gzip -9kf dists/stable/main/binary-amd64/Packages
  cat > release.conf <<CONF
APT::FTPArchive::Release::Origin "IUK Browser";
APT::FTPArchive::Release::Label "IUK Browser";
APT::FTPArchive::Release::Suite "stable";
APT::FTPArchive::Release::Codename "stable";
APT::FTPArchive::Release::Architectures "amd64";
APT::FTPArchive::Release::Components "main";
APT::FTPArchive::Release::Description "IUK Browser packages";
CONF
  apt-ftparchive -c release.conf release dists/stable > dists/stable/Release
  rm -f release.conf dists/stable/InRelease dists/stable/Release.gpg
  sign --clearsign -o dists/stable/InRelease dists/stable/Release
  sign -abs -o dists/stable/Release.gpg dists/stable/Release )
cat > "$APT/iuk-browser.sources" <<SRC
Types: deb
URIs: $SITE_URL/apt
Suites: stable
Components: main
Architectures: amd64
Signed-By: /etc/apt/keyrings/iuk-browser.gpg
SRC

# ---------------------------------------------------------------- dnf / yum
RPM="$SITE/rpm"; mkdir -p "$RPM"
cp -f "$PKG"/*.rpm "$RPM"/
createrepo_c --quiet --update "$RPM"
rm -f "$RPM/repodata/repomd.xml.asc"
sign --detach-sign --armor -o "$RPM/repodata/repomd.xml.asc" "$RPM/repodata/repomd.xml"
cat > "$RPM/iuk-browser.repo" <<REPO
[iuk-browser]
name=IUK Browser
baseurl=$SITE_URL/rpm
enabled=1
gpgcheck=${RPM_SIGNED:-0}
repo_gpgcheck=1
gpgkey=$SITE_URL/iuk-browser.asc
REPO

# ---------------------------------------------------------------- keys + landing page
gpg --batch --quiet --export "$KEYID" > "$SITE/iuk-browser.gpg"
gpg --batch --quiet --armor --export "$KEYID" > "$SITE/iuk-browser.asc"
touch "$SITE/.nojekyll"
cat > "$SITE/index.html" <<HTML
<!doctype html><meta charset="utf-8"><title>IUK Browser packages</title>
<body style="font:16px system-ui;max-width:46rem;margin:2rem auto;padding:0 1rem">
<h1>IUK Browser</h1>
<h2>Debian / Ubuntu (apt)</h2>
<pre>sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL $SITE_URL/iuk-browser.gpg | sudo tee /etc/apt/keyrings/iuk-browser.gpg &gt;/dev/null
curl -fsSL $SITE_URL/apt/iuk-browser.sources | sudo tee /etc/apt/sources.list.d/iuk-browser.sources &gt;/dev/null
sudo apt update &amp;&amp; sudo apt install iuk-browser</pre>
<h2>Fedora / RHEL (dnf)</h2>
<pre>sudo curl -fsSL -o /etc/yum.repos.d/iuk-browser.repo $SITE_URL/rpm/iuk-browser.repo
sudo dnf install iuk-browser</pre>
<p>Updates arrive with your normal <code>apt upgrade</code> / <code>dnf upgrade</code>. Signing key fingerprint: <code>$KEYID</code></p>
</body>
HTML
echo "site ready in $SITE (key $KEYID)"
