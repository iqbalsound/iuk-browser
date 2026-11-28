"""Tracker and ad blocking: a small filter engine for the common Adblock Plus rule syntax.

Supported: domain rules (||example.com^, ||example.com/path), plain substring rules, exceptions (@@...), the options
$third-party / $~third-party and resource types ($script,image,stylesheet,xmlhttprequest,subdocument,media,font,ping,
websocket,object,other). Cosmetic (element-hiding) rules, regex rules, wildcards and rules with options that cannot be
honored exactly ($domain=, $redirect=, ...) are skipped rather than approximated, so the engine errs on the side of
NOT breaking pages. Page navigations (the main frame) are never blocked.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

TYPES = frozenset({"script", "image", "stylesheet", "xmlhttprequest", "subdocument", "media", "font", "ping", "websocket", "object", "other"})
_SLD = {"co", "com", "org", "net", "gov", "edu", "ac", "or", "ne"}      # heuristic for co.uk, com.au, ...
_OPT_OK = re.compile(r"^[~a-z0-9_,=|.\-]+$")
_DOMAIN_RULE = re.compile(r"^\|\|([a-z0-9][a-z0-9.\-]*)(\^|/|$)(.*)$")
MAX_SUBSTRING_RULES = 5000


def registrable(host: str) -> str:
    labels = host.lower().strip(".").split(".")
    if len(labels) <= 2:
        return ".".join(labels)
    if len(labels[-1]) == 2 and labels[-2] in _SLD:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


@dataclass(frozen=True)
class Rule:
    pattern: str                    # host (domain rules) or lower-case substring
    path: str                       # required path prefix for domain rules ("" = any)
    domain: bool
    exception: bool
    third_party: bool | None
    types: frozenset | None


def parse_rule(line: str) -> Rule | None:
    line = line.strip()
    if not line or line[0] in "![" or any(m in line for m in ("##", "#@#", "#?#", "#$#")):
        return None
    exception = line.startswith("@@")
    if exception:
        line = line[2:]
    third_party: bool | None = None
    types: set[str] = set()
    if "$" in line:
        body, _, opts = line.rpartition("$")
        if _OPT_OK.match(opts):
            for o in opts.split(","):
                if o == "third-party":
                    third_party = True
                elif o == "~third-party":
                    third_party = False
                elif o in TYPES:
                    types.add(o)
                else:
                    return None                  # unsupported option: skip the whole rule
            line = body
    if not line or line.startswith("/") and line.endswith("/") and len(line) > 2:
        return None                              # regex rule
    if "*" in line:
        return None
    m = _DOMAIN_RULE.match(line.lower())
    if m:
        host, sep, rest = m.groups()
        rest = rest.rstrip("^")
        if "^" in rest or "|" in rest:
            return None
        path = rest if rest.startswith("/") else ("/" + rest if rest else "")
        return Rule(host, path if sep == "/" or rest else "", True, exception, third_party, frozenset(types) or None)
    if line.startswith("|") or line.endswith("|"):
        return None                              # start/end anchors are not supported
    pat = line.lower().rstrip("^")
    if len(pat) < 4 or "^" in pat:
        return None
    return Rule(pat, "", False, exception, third_party, frozenset(types) or None)


class Blocker:
    def __init__(self):
        self.enabled = True
        self.allow_sites: set[str] = set()
        self.rule_count = 0
        self.blocked: dict[str, int] = {}                          # first-party host -> blocked requests
        self._dom_block: dict[str, list[Rule]] = {}
        self._dom_allow: dict[str, list[Rule]] = {}
        self._sub_block: list[Rule] = []
        self._sub_allow: list[Rule] = []

    def clear(self) -> None:
        self.rule_count = 0
        self._dom_block, self._dom_allow, self._sub_block, self._sub_allow = {}, {}, [], []

    def load_text(self, text: str) -> int:
        added = 0
        for line in text.splitlines():
            r = parse_rule(line)
            if r is None:
                continue
            if r.domain:
                (self._dom_allow if r.exception else self._dom_block).setdefault(r.pattern, []).append(r)
            else:
                lst = self._sub_allow if r.exception else self._sub_block
                if len(lst) >= MAX_SUBSTRING_RULES:
                    continue
                lst.append(r)
            added += 1
        self.rule_count += added
        return added

    def load_file(self, path) -> int:
        return self.load_text(Path(path).read_text("utf-8", errors="replace"))

    def site_allowed(self, first_party_host: str) -> bool:
        h = (first_party_host or "").lower()
        return any(h == a or h.endswith("." + a) for a in self.allow_sites)

    @staticmethod
    def _applies(r: Rule, third: bool, rtype: str, path: str) -> bool:
        return ((r.third_party is None or r.third_party == third) and (r.types is None or rtype in r.types)
                and (not r.path or path.startswith(r.path)))

    def should_block(self, url: str, first_party_host: str, rtype: str = "other") -> bool:
        if not self.enabled or self.rule_count == 0:
            return False
        try:
            u = urlparse(url)
        except ValueError:
            return False
        host = (u.hostname or "").lower()
        if not host or u.scheme not in ("http", "https", "ws", "wss") or self.site_allowed(first_party_host):
            return False
        fp = (first_party_host or "").lower()
        third = bool(fp) and registrable(fp) != registrable(host)
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        low = url.lower()
        labels = host.split(".")
        suffixes = [".".join(labels[i:]) for i in range(len(labels))]
        for suf in suffixes:
            if any(self._applies(r, third, rtype, path) for r in self._dom_allow.get(suf, ())):
                return False
        if any(r.pattern in low and self._applies(r, third, rtype, path) for r in self._sub_allow):
            return False
        for suf in suffixes:
            if any(self._applies(r, third, rtype, path) for r in self._dom_block.get(suf, ())):
                return True
        return any(r.pattern in low and self._applies(r, third, rtype, path) for r in self._sub_block)
