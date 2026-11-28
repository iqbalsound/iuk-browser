"""Signed update channel.

A release publishes `<channel>.json` (the manifest) next to `<channel>.json.sig`, an Ed25519 signature
over the manifest bytes. The app trusts only the public keys compiled into `update_keys.py`, so a hijacked
download host cannot push a malicious update: it cannot forge the signature. Installers are additionally
checked against the SHA-256 in the (signed) manifest before they are run.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .. import __version__


class UpdateError(Exception):
    pass


def parse_version(v: str) -> tuple:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?", v.strip())
    if not m:
        raise UpdateError(f"Bad version {v!r}")
    major, minor, patch, pre = m.groups()
    # a release sorts after any of its pre-releases
    return (int(major), int(minor), int(patch), 1 if pre is None else 0, pre or "")


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def platform_key() -> str:
    if sys.platform.startswith("win"):
        return "windows-x64"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def verify_manifest(data: bytes, signature_b64: str, public_keys: list[str]) -> dict:
    if not public_keys:
        raise UpdateError("No update signing keys are configured in this build")
    try:
        sig = base64.b64decode(signature_b64.strip())
    except ValueError:
        raise UpdateError("Malformed update signature") from None
    for k in public_keys:
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(k)).verify(sig, data)
            return json.loads(data)
        except (InvalidSignature, ValueError):
            continue
    raise UpdateError("The update manifest signature is not valid")


@dataclass
class UpdateInfo:
    version: str
    notes: str
    url: str
    sha256: str
    size: int
    channel: str
    kind: str          # "installer" (Windows: can be applied automatically) or "package"/"page" (manual / package manager)


class Updater:
    def __init__(self, base_url: str, public_keys: list[str], current: str = __version__, channel: str = "stable", fetch=None):
        self.base, self.keys, self.current, self.channel = base_url.rstrip("/"), public_keys, current, channel
        self._fetch = fetch or self._http

    @staticmethod
    def _http(url: str, limit: int = 5_000_000) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": f"IUK-Browser/{__version__}"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read(limit + 1)
        except OSError as e:
            raise UpdateError(f"Cannot reach the update server ({e})") from None
        if len(data) > limit:
            raise UpdateError("Update response too large")
        return data

    def check(self) -> UpdateInfo | None:
        manifest_bytes = self._fetch(f"{self.base}/{self.channel}.json")
        sig = self._fetch(f"{self.base}/{self.channel}.json.sig").decode()
        m = verify_manifest(manifest_bytes, sig, self.keys)
        if m.get("channel") != self.channel:
            raise UpdateError("Manifest is for a different channel")
        if not is_newer(m["version"], self.current):
            return None
        asset = (m.get("assets") or {}).get(platform_key())
        if not asset:
            return UpdateInfo(m["version"], m.get("notes", ""), m.get("page", ""), "", 0, self.channel, "page")
        return UpdateInfo(m["version"], m.get("notes", ""), asset["url"], asset.get("sha256", ""), int(asset.get("size", 0)),
                          self.channel, asset.get("kind", "installer"))

    def download(self, info: UpdateInfo, dest_dir: Path, progress=None) -> Path:
        if info.kind != "installer" or not info.sha256:
            raise UpdateError("This update is installed by your package manager or from the download page")
        if not info.url.lower().startswith("https://"):
            raise UpdateError("Refusing a non-HTTPS download")
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / Path(info.url.split("?")[0]).name
        h = hashlib.sha256()
        req = urllib.request.Request(info.url, headers={"User-Agent": f"IUK-Browser/{__version__}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
                total = int(r.headers.get("Content-Length") or info.size or 0)
                done = 0
                while chunk := r.read(1 << 16):
                    h.update(chunk)
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        except OSError as e:
            path.unlink(missing_ok=True)
            raise UpdateError(f"Download failed ({e})") from None
        if h.hexdigest() != info.sha256.lower():
            path.unlink(missing_ok=True)
            raise UpdateError("The downloaded installer does not match the signed checksum")
        return path


def run_installer(path: Path) -> None:
    """Windows: start the NSIS installer silently (per-user install, no admin prompt) and let the app exit."""
    if not sys.platform.startswith("win"):
        raise UpdateError("Automatic install is only available on Windows")
    flags = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(path), "/S", "/UPDATE"], creationflags=flags, close_fds=True)  # noqa: S603
