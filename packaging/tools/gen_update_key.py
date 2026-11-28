#!/usr/bin/env python3
"""Generate the Ed25519 key pair that signs update manifests.

    python3 packaging/tools/gen_update_key.py

Put the PRIVATE line into the GitHub secret UPDATE_SIGNING_KEY (never commit it) and the PUBLIC value into
src/iuk_browser/core/update_keys.py (UPDATE_PUBLIC_KEYS). Keep a backup of the private key somewhere safe:
if it is lost, installed copies can no longer trust new updates.
"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

k = Ed25519PrivateKey.generate()
priv = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
print("PRIVATE (GitHub secret UPDATE_SIGNING_KEY):", base64.b64encode(priv).decode())
print("PUBLIC  (update_keys.py UPDATE_PUBLIC_KEYS):", base64.b64encode(pub).decode())
