"""Password CSV import/export (Firefox, Chrome and Edge column layouts)."""
from __future__ import annotations

import csv
import io

from .util import host_from


def parse_logins(text: str) -> list[dict]:
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    if not rows:
        return []
    head = [h.strip().lower() for h in rows[0]]

    def ix(*names):
        return next((i for i, h in enumerate(head) if h in names), -1)

    iu, iun, ip, inn = ix("url", "origin", "hostname", "website", "login_uri"), ix("username", "login", "login_username", "user"), \
        ix("password", "login_password"), ix("note", "notes")
    if iu < 0 or ip < 0:
        raise ValueError("CSV needs url and password columns")
    out = []
    for r in rows[1:]:
        if len(r) > max(iu, ip) and r[iu] and r[ip]:
            out.append({"host": host_from(r[iu]), "username": r[iun] if iun >= 0 and iun < len(r) else "",
                        "password": r[ip], "notes": r[inn] if inn >= 0 and inn < len(r) else ""})
    return out


def export_logins(items: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    w.writerow(["url", "username", "password", "note"])
    for l in items:
        w.writerow(["https://" + l["host"], l["username"], l["password"], l["notes"]])
    return buf.getvalue()
