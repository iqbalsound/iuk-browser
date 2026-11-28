"""Device pairing code (`IUKB1:` + base64url JSON). Identical to the extension's format."""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from urllib.parse import urlparse

PREFIX = "IUKB1:"


class PairingError(ValueError):
    pass


@dataclass(frozen=True)
class Pairing:
    username: str
    secret: str
    server: str


def encode(username: str, secret: str, server: str = "") -> str:
    raw = json.dumps({"u": username, "k": secret, "s": server or ""}, separators=(",", ":"), ensure_ascii=False).encode()
    return PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(text: str) -> Pairing:
    text = (text or "").strip()
    if not text.startswith(PREFIX):
        raise PairingError("This is not an IUK Browser pairing code")
    body = text[len(PREFIX):]
    try:
        obj = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception as exc:  # noqa: BLE001
        raise PairingError("The pairing code is damaged") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("u"), str) or not obj["u"].strip() \
            or not isinstance(obj.get("k"), str) or len(obj["k"]) < 12:
        raise PairingError("The pairing code is incomplete")
    server = ""
    if obj.get("s"):
        u = urlparse(str(obj["s"]))
        if u.scheme not in ("http", "https") or not u.netloc:
            raise PairingError("The pairing code has an invalid server address")
        server = str(obj["s"]).rstrip("/")
    return Pairing(obj["u"].strip(), obj["k"], server)


# ---------------------------------------------------------------- one-time pairing (IUKB2)
# The QR carries a random pairing id and a random ONE-TIME key, never the account key. The account details are
# uploaded to the relay encrypted with that one-time key, can be fetched exactly once, and expire after 120 s.
PREFIX2 = "IUKB2:"
TTL_SECONDS = 120


@dataclass(frozen=True)
class Offer:
    server: str
    pid: str          # 32 hex chars
    key: bytes        # 32-byte one-time key


def encode_offer(server: str, pid: str, key: bytes) -> str:
    raw = json.dumps({"s": server, "p": pid, "k": base64.urlsafe_b64encode(key).decode().rstrip("=")}, separators=(",", ":")).encode()
    return PREFIX2 + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_offer(text: str) -> Offer:
    text = (text or "").strip()
    if not text.startswith(PREFIX2):
        raise PairingError("This is not a one-time IUK Browser pairing code")
    body = text[len(PREFIX2):]
    try:
        obj = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        key = base64.urlsafe_b64decode(obj["k"] + "=" * (-len(obj["k"]) % 4))
        pid, server = str(obj["p"]), str(obj["s"]).rstrip("/")
    except Exception as exc:  # noqa: BLE001
        raise PairingError("The pairing code is damaged") from exc
    u = urlparse(server)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise PairingError("The pairing code has an invalid server address")
    if len(key) != 32 or len(pid) != 32 or any(c not in "0123456789abcdef" for c in pid):
        raise PairingError("The pairing code is incomplete")
    return Offer(server, pid, key)


def kind(text: str) -> str:
    """'direct' (IUKB1: contains the key itself), 'offer' (IUKB2: one-time) or '' (not a pairing code)."""
    t = (text or "").strip()
    return "offer" if t.startswith(PREFIX2) else "direct" if t.startswith(PREFIX) else ""
