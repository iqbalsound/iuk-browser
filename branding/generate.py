#!/usr/bin/env python3
"""Regenerates branding/generated/ (committed), the extension icons and the preview sheet.

    pip install cairosvg pillow fonttools
    python3 branding/generate.py
"""
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

import brand as B

ROOT = B.HERE.parent
GEN = B.HERE / "generated"
EXT_ICONS = ROOT / "extension" / "icons"
LINUX_SIZES = [16, 22, 24, 32, 48, 64, 128, 256, 512]
WIN_SIZES = [16, 24, 32, 48, 64, 128, 256]


def main():
    if GEN.exists():
        shutil.rmtree(GEN)
    # Linux hicolor theme (taskbar, minimized window, launcher, alt-tab, file manager)
    for s in LINUX_SIZES:
        B.save_png(B.mark("app", s), GEN / "hicolor" / f"{s}x{s}" / "apps" / f"{B.CFG['slug']}.png")
    (GEN / "hicolor" / "scalable" / "apps").mkdir(parents=True, exist_ok=True)
    shutil.copy(B.SRC / "logo.svg", GEN / "hicolor" / "scalable" / "apps" / f"{B.CFG['slug']}.svg")
    # Windows icons (exe/installer/shortcut, taskbar, jump list, file associations)
    B.save_ico(GEN / "iuk-browser.ico", "app", WIN_SIZES)
    B.save_ico(GEN / "private.ico", "private", WIN_SIZES)
    B.save_ico(GEN / "newtab.ico", "newtab", [16, 32])
    B.save_ico(GEN / "newwindow.ico", "newwindow", [16, 32])
    B.save_ico(GEN / "document.ico", "document", [16, 32, 48, 256])
    B.save_icns(GEN / "iuk-browser.icns", "app")
    # Installer art
    B.wiz_header(150, 57).save(GEN / "installer-header.bmp")
    B.splash(164, 314, logo_frac=0.62).save(GEN / "installer-side.bmp")
    # Wordmark + store-style tiles
    (GEN / "wordmark.svg").write_text(B.wordmark_svg())
    B.save_png(B.tile(310, 150, "app", 0.7), GEN / "tile-wide.png")
    B.save_png(B.splash(1280, 640, 0.34), GEN / "social-preview.png")  # GitHub repo social card
    # Extension (toolbar button, add-on manager, options page)
    EXT_ICONS.mkdir(parents=True, exist_ok=True)
    for f in EXT_ICONS.glob("*"):
        f.unlink()
    for s in (16, 32, 48, 96, 128):
        B.save_png(B.mark("app", s), EXT_ICONS / f"icon-{s}.png")
    shutil.copy(B.SRC / "logo-small.svg", EXT_ICONS / "icon.svg")
    sheet()
    print("generated:", sum(1 for _ in GEN.rglob("*") if _.is_file()), "files in", GEN)


def sheet():
    """branding/preview.png: every variant at the sizes people actually see."""
    variants = [("app", "App"), ("private", "Private"), ("newtab", "New tab"), ("newwindow", "New window"),
                ("document", "Document"), ("pdf", "PDF")]
    W, H = 1290, 560
    img = Image.new("RGB", (W, H), (240, 242, 248))
    d = ImageDraw.Draw(img)
    d.text((24, 16), f"{B.NAME} icon set", fill=(11, 23, 64))
    x = 24
    for v, label in variants:
        big = B.mark(v, 128)
        img.paste(big, (x, 48), big)
        d.text((x, 182), label, fill=(60, 70, 110))
        sx = x
        for s in (16, 24, 32, 48):
            m = B.mark(v, s)
            img.paste(m, (sx, 210), m)
            sx += s + 6
        x += 190
    # on dark + light backgrounds, as in a taskbar
    for i, (bg, name) in enumerate([((32, 33, 36), "dark taskbar"), ((250, 250, 250), "light taskbar")]):
        d.rectangle([24, 280 + i * 70, 560, 336 + i * 70], fill=bg)
        px = 36
        for s in (16, 24, 32, 48):
            m = B.mark("app", s)
            img.paste(m, (px, 308 + i * 70 - s // 2), m)
            px += s + 18
        d.text((330, 300 + i * 70), name, fill=(180, 180, 190) if i == 0 else (60, 60, 70))
    # installer + about art
    for art, pos in [(B.splash(164, 314, 0.62), (600, 280)), (B.splash(300, 236, 0.5), (790, 280)),
                     (B.wiz_header(150, 57), (1110, 280))]:
        img.paste(art, pos)
    wm = Image.new("RGB", (372, 99), (255, 255, 255))
    import cairosvg, io
    png = cairosvg.svg2png(bytestring=(GEN / "wordmark.svg").read_text().replace("context-fill", "#0b1740").encode(),
                           output_width=372, output_height=99)
    w = Image.open(io.BytesIO(png)).convert("RGBA")
    wm.paste(w, (0, 0), w)
    img.paste(wm, (24, 450))
    img.save(B.HERE / "preview.png")


if __name__ == "__main__":
    main()
