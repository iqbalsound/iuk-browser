"""Color invert and page filters. The same logic lives in resources/js/display.js (kept in sync by a test)."""
from __future__ import annotations

DEFAULT = {"mode": "off", "sites": [], "brightness": 100, "contrast": 100, "sepia": 0, "keepMedia": True}


def normalize(s: dict | None) -> dict:
    out = dict(DEFAULT)
    out.update(s or {})
    out["sites"] = [str(x).lower() for x in out.get("sites", [])]
    return out


def is_inverted(s: dict, host: str) -> bool:
    s = normalize(s)
    return s["mode"] == "all" or (s["mode"] == "sites" and host.lower() in s["sites"])


def css(s: dict, host: str) -> str:
    s = normalize(s)
    on = is_inverted(s, host)
    f = []
    if on:
        f.append("invert(1) hue-rotate(180deg)")
    if s["brightness"] != 100:
        f.append(f"brightness({s['brightness']}%)")
    if s["contrast"] != 100:
        f.append(f"contrast({s['contrast']}%)")
    if s["sepia"] > 0:
        f.append(f"sepia({s['sepia']}%)")
    if not f:
        return ""
    out = "html{filter:" + " ".join(f) + " !important;" + ("background:#fff;" if on else "") + "}"
    if on and s["keepMedia"]:
        out += 'img,picture,video,canvas,[style*="background-image"]{filter:invert(1) hue-rotate(180deg) !important;}'
    return out
