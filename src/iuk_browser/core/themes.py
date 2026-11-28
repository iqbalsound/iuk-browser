"""Application themes: (background, text, accent) triples expanded into a full palette."""
from __future__ import annotations

THEMES = [
    {"id": "light", "name": "Light", "bg": "#f0f0f4", "fg": "#15141a", "accent": "#0060df"},
    {"id": "dark", "name": "Dark", "bg": "#1c1b22", "fg": "#fbfbfe", "accent": "#00ddff"},
    {"id": "midnight", "name": "Midnight", "bg": "#0b1020", "fg": "#e6edf7", "accent": "#7aa2ff"},
    {"id": "nord", "name": "Nord", "bg": "#2e3440", "fg": "#eceff4", "accent": "#88c0d0"},
    {"id": "solarized-dark", "name": "Solarized Dark", "bg": "#002b36", "fg": "#93a1a1", "accent": "#b58900"},
    {"id": "solarized-light", "name": "Solarized Light", "bg": "#fdf6e3", "fg": "#586e75", "accent": "#268bd2"},
    {"id": "contrast", "name": "High contrast", "bg": "#000000", "fg": "#ffffff", "accent": "#ffff00"},
]


def hex2rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    n = int(h, 16)
    return (n >> 16) & 255, (n >> 8) & 255, n & 255


def rgb2hex(c) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in c)


def mix(a: str, b: str, t: float) -> str:
    return rgb2hex([x + (y - x) * t for x, y in zip(hex2rgb(a), hex2rgb(b))])


def luminance(h: str) -> float:
    r, g, b = (v / 255 for v in hex2rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def make_palette(bg: str, fg: str, accent: str) -> dict:
    dark = luminance(bg) < 0.5
    return {
        "dark": dark, "window": bg, "text": fg, "accent": accent,
        "base": mix(bg, fg, 0.06), "alt_base": mix(bg, fg, 0.10), "button": mix(bg, fg, 0.12),
        "border": mix(bg, fg, 0.25), "disabled": mix(bg, fg, 0.45),
        "on_accent": "#000000" if luminance(accent) > 0.5 else "#ffffff",
    }


def resolve(setting: dict | None) -> dict | None:
    """Setting {"id": "dark"} | {"id": "custom", bg, fg, accent} | {"id": "system"} -> palette or None (system)."""
    setting = setting or {"id": "system"}
    if setting["id"] == "system":
        return None
    if setting["id"] == "custom":
        return make_palette(setting["bg"], setting["fg"], setting["accent"])
    t = next((t for t in THEMES if t["id"] == setting["id"]), None)
    return make_palette(t["bg"], t["fg"], t["accent"]) if t else None
