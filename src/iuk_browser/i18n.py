"""Tiny translation layer: JSON catalogs map the English source string to a translation.

    from iuk_browser.i18n import tr
    tr("Hides in {} s", 30)
Missing strings fall back to English, so a partial catalog never breaks the UI.
"""
from __future__ import annotations

import json
import locale
import os
from pathlib import Path

LANGS = {"en": "English", "ur": "اردو", "ar": "العربية", "fr": "Français", "es": "Español", "de": "Deutsch", "zh_CN": "简体中文"}
RTL = {"ar", "ur"}
_DIR = Path(__file__).parent / "i18n"
_catalog: dict[str, str] = {}
_lang = "en"


def detect() -> str:
    cand = (os.environ.get("IUK_LANG") or os.environ.get("LANGUAGE") or os.environ.get("LC_ALL") or os.environ.get("LANG") or "").split(":")[0]
    if not cand:
        try:
            cand = locale.getlocale()[0] or ""
        except (ValueError, TypeError):
            cand = ""
    cand = cand.split(".")[0].replace("-", "_")
    if cand in LANGS:
        return cand
    if cand.startswith("zh"):
        return "zh_CN"
    base = cand.split("_")[0]
    return base if base in LANGS else "en"


def set_language(code: str) -> str:
    global _catalog, _lang
    code = detect() if code in ("auto", "", None) else code
    if code not in LANGS:
        code = "en"
    _lang = code
    p = _DIR / f"{code}.json"
    _catalog = json.loads(p.read_text("utf-8")) if code != "en" and p.exists() else {}
    return code


def language() -> str:
    return _lang


def is_rtl(code: str | None = None) -> bool:
    return (code or _lang) in RTL


def tr(text: str, *args) -> str:
    s = _catalog.get(text, text)
    return s.format(*args) if args else s
