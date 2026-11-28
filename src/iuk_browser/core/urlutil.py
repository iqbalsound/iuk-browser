"""Address-bar input -> URL (or search)."""
from __future__ import annotations

import re
from urllib.parse import quote

_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*):")
_HOSTPORT = re.compile(r"^[\w.-]+:\d+(/.*)?$")
_ALLOWED = {"http", "https", "file", "about", "view-source", "data", "ftp", "iuk"}


def resolve(text: str, search_url) -> str:
    """Returns the URL to load. `search_url(query)` builds a search URL. javascript: is never loaded from the bar."""
    t = (text or "").strip()
    if not t:
        return "about:blank"
    m = _SCHEME.match(t)
    if m and not _HOSTPORT.match(t):
        scheme = m.group(1).lower()
        return t if scheme in _ALLOWED else search_url(t)
    if " " not in t and ("." in t or t.lower().startswith("localhost") or re.fullmatch(r"\[[0-9a-fA-F:]+\](:\d+)?(/.*)?", t) or _HOSTPORT.match(t)):
        if re.fullmatch(r"\d+(\.\d+)*", t) and t.count(".") < 3:   # "3.14" is a query, not a host
            return search_url(t)
        return "http://" + t if re.match(r"^(localhost|127\.|192\.168\.|10\.|\[)", t) else "https://" + t
    return search_url(t)


def display_url(url: str) -> str:
    return url[:-1] if url.endswith("/") and url.count("/") == 3 else url
