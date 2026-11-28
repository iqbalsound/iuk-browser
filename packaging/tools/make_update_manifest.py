#!/usr/bin/env python3
"""Build and sign the update manifest for a release.

    UPDATE_SIGNING_KEY=<base64 private> python3 packaging/tools/make_update_manifest.py \
        --version 2.1.0 --channel stable --assets dist --out site/update \
        --download-base https://github.com/OWNER/iuk-browser/releases/download/v2.1.0 \
        --page https://github.com/OWNER/iuk-browser/releases/tag/v2.1.0 --notes-file notes.md

Writes <channel>.json and <channel>.json.sig (Ed25519 over the exact bytes of the JSON file).
"""
import argparse
import base64
import hashlib
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--channel", default="stable", choices=["stable", "beta"])
    ap.add_argument("--assets", required=True, type=Path, help="directory holding the release files")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--download-base", required=True)
    ap.add_argument("--page", required=True)
    ap.add_argument("--notes-file", type=Path)
    a = ap.parse_args()

    key = os.environ.get("UPDATE_SIGNING_KEY", "").strip()
    if not key:
        print("UPDATE_SIGNING_KEY is not set; refusing to publish an unsigned manifest", file=sys.stderr)
        return 2
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(key))

    assets = {"linux": {"url": a.page, "kind": "page"}, "macos": {"url": a.page, "kind": "page"}}
    exe = sorted(a.assets.glob("*-setup.exe"))
    if exe:
        data = exe[0].read_bytes()
        assets["windows-x64"] = {"url": f"{a.download_base.rstrip('/')}/{exe[0].name}", "kind": "installer",
                                 "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    manifest = {"channel": a.channel, "version": a.version, "page": a.page,
                "notes": a.notes_file.read_text("utf-8").strip()[:2000] if a.notes_file and a.notes_file.exists() else "",
                "assets": assets}
    a.out.mkdir(parents=True, exist_ok=True)
    body = json.dumps(manifest, indent=1, sort_keys=True).encode()
    (a.out / f"{a.channel}.json").write_bytes(body)
    (a.out / f"{a.channel}.json.sig").write_text(base64.b64encode(priv.sign(body)).decode())
    print(f"wrote {a.out}/{a.channel}.json (+ .sig), windows asset: {'yes' if exe else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
