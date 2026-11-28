"""Small shared helpers (host matching, password generation, time)."""
from __future__ import annotations

import secrets
import time
from urllib.parse import urlparse


def now_ms() -> int:
    return int(time.time() * 1000)


def host_from(value: str) -> str:
    v = (value or "").strip()
    try:
        u = urlparse(v if "://" in v else "https://" + v)
        return (u.hostname or v).removeprefix("www.").lower()
    except ValueError:
        return v.lower()


def host_matches(entry_host: str, tab_host: str) -> bool:
    a, b = host_from(entry_host), host_from(tab_host)
    return bool(a) and (a == b or b.endswith("." + a))


_SETS = ("abcdefghijkmnopqrstuvwxyz", "ABCDEFGHJKLMNPQRSTUVWXYZ", "23456789", "!@#$%^&*-_=+?")


def gen_password(length: int = 20) -> str:
    length = max(8, min(128, length))
    alphabet = "".join(_SETS)
    while True:
        p = "".join(secrets.choice(alphabet) for _ in range(length))
        if all(any(c in s for c in p) for s in _SETS):
            return p
