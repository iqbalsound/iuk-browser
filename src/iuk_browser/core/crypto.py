"""Key derivation and authenticated encryption.

Wire-compatible with the IUK Browser extension (1.1+): same Argon2id parameters, salt, key/token split and
the `v1.<iv>.<ciphertext>` AES-256-GCM container, so one account works on both editions.

The sync server only ever sees `token` (a bearer secret) and ciphertext. The AES key and the token are
independent halves of one 64-byte KDF output, so knowing the token reveals nothing about the key.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KDF_ID = "argon2id-v2"
# Production parameters. Tests may lower them via the module attribute; never change them for real data.
PARAMS = {"memory_kib": 65536, "passes": 3, "lanes": 1}


class DecryptError(Exception):
    """Wrong key or damaged/forged data."""


@dataclass(frozen=True)
class Keys:
    key: bytes          # 32-byte AES key (never leaves the device)
    token: str          # 64 hex chars, sent to the relay as the bearer secret
    kdf: str = KDF_ID


def derive_keys(username: str, secret: str) -> Keys:
    salt = hashlib.sha256(b"iuk-browser-v2|" + username.strip().lower().encode()).digest()
    raw = hash_secret_raw(
        secret.encode(), salt, time_cost=PARAMS["passes"], memory_cost=PARAMS["memory_kib"],
        parallelism=PARAMS["lanes"], hash_len=64, type=Type.ID,
    )
    return Keys(key=raw[:32], token=raw[32:].hex())


def encrypt(key: bytes, obj) -> str:
    iv = os.urandom(12)
    data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()
    ct = AESGCM(key).encrypt(iv, data, None)  # ciphertext || 16-byte tag, same layout as WebCrypto
    return "v1." + base64.b64encode(iv).decode() + "." + base64.b64encode(ct).decode()


def decrypt(key: bytes, blob: str):
    try:
        ver, iv, ct = blob.strip().split(".")
        if ver != "v1":
            raise ValueError("version")
        return json.loads(AESGCM(key).decrypt(base64.b64decode(iv), base64.b64decode(ct), None))
    except (InvalidTag, ValueError, TypeError) as exc:
        raise DecryptError("wrong key or damaged data") from exc
