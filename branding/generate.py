#!/usr/bin/env python3
"""Regenerates every icon from branding/src/*.svg.

    pip install -r branding/requirements.txt
    python3 branding/generate.py

Writes branding/generated/ (Windows .ico, installer art, hicolor PNGs for DEB/RPM, social card) and the
runtime icons in src/iuk_browser/resources/icons/.
"""
import shutil
from pathlib import Path

import brand as B

ROOT = B.HERE.parent
GEN = B.HERE / "generated"
RES = ROOT / "src" / "iuk_browser" / "resources" / "icons"
LINUX_SIZES = [16, 22, 24, 32, 48, 64, 128, 256, 512]
WIN_SIZES = [16, 24, 32, 48, 64, 128, 256]


def main():
    shutil.rmtree(GEN, ignore_errors=True)
    for s in LINUX_SIZES:
        B.save_png(B.mark("app", s), GEN / "hicolor" / f"{s}x{s}" / "apps" / f"{B.CFG['slug']}.png")
    (GEN / "hicolor" / "scalable" / "apps").mkdir(parents=True, exist_ok=True)
    shutil.copy(B.SRC / "logo.svg", GEN / "hicolor" / "scalable" / "apps" / f"{B.CFG['slug']}.svg")
    B.save_ico(GEN / "iuk-browser.ico", "app", WIN_SIZES)
    B.save_ico(GEN / "private.ico", "private", WIN_SIZES)
    B.save_icns(GEN / "iuk-browser.icns", "app")
    B.wiz_header(150, 57).save(GEN / "installer-header.bmp")
    B.splash(164, 314, logo_frac=0.62).save(GEN / "installer-side.bmp")
    B.save_png(B.splash(1280, 640, 0.34), GEN / "social-preview.png")
    (GEN / "wordmark.svg").write_text(B.wordmark_svg())
    RES.mkdir(parents=True, exist_ok=True)
    for f in RES.glob("*"):
        f.unlink()
    for s in (16, 32, 48, 64, 128, 256, 512):
        B.save_png(B.mark("app", s), RES / f"iuk-browser-{s}.png")
    for s in (32, 64, 128):
        B.save_png(B.mark("private", s), RES / f"private-{s}.png")
    shutil.copy(B.SRC / "logo.svg", RES / "iuk-browser.svg")
    print("generated", sum(1 for _ in GEN.rglob("*") if _.is_file()), "files +", sum(1 for _ in RES.glob("*")), "runtime icons")


if __name__ == "__main__":
    main()
