"""Rendering library for IUK Browser branding. Everything is drawn from the SVG files in branding/src/.

Requires: pip install cairosvg pillow fonttools
"""
import io
import json
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SRC = HERE / "src"
CFG = json.loads((HERE / "brand.json").read_text())
NAME = CFG["name"]
C = CFG["colors"]

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def font_path():
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return p
    raise SystemExit("No bold sans font found; install fonts-dejavu-core")


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------- marks
def svg_img(name, w, h=None):
    h = h or w
    png = cairosvg.svg2png(url=str(SRC / f"{name}.svg"), output_width=w, output_height=h)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def classify(rel):
    r = rel.lower()
    if "private" in r or "pbmode" in r:
        return "private"
    if "document_pdf" in r:
        return "pdf"
    if "document" in r:
        return "document"
    if "newtab" in r:
        return "newtab"
    if "newwindow" in r:
        return "newwindow"
    return "app"


def mark(variant, size):
    """The icon for a variant at a pixel size. Small sizes use a simplified, bolder drawing."""
    small = size <= 32
    name = {
        "app": "logo-small" if small else "logo",
        "private": "logo-private-small" if small else "logo-private",
        "newtab": "newtab",
        "newwindow": "newwindow",
        "document": "document",
        "pdf": "document_pdf",
    }[variant]
    return svg_img(name, size)


def tile(w, h, variant="app", scale=0.6, bg=None, dy=0.0):
    """Mark centered on a w x h canvas (transparent unless bg is given)."""
    canvas = Image.new("RGBA", (w, h), bg or (0, 0, 0, 0))
    s = max(8, int(min(w, h) * scale))
    m = mark(variant, s)
    canvas.alpha_composite(m, ((w - s) // 2, int((h - s) / 2 + h * dy)))
    return canvas


def gradient(w, h, top, bottom):
    t, b = hex2rgb(top), hex2rgb(bottom)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        k = y / max(1, h - 1)
        row = tuple(int(t[i] + (b[i] - t[i]) * k) for i in range(3))
        for x in range(w):
            px[x, y] = row
    return img


def text_centered(img, text, y, size, fill=(255, 255, 255)):
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(font_path(), size)
    w = d.textlength(text, font=f)
    d.text(((img.width - w) / 2, y), text, font=f, fill=fill)


def splash(w, h, logo_frac=0.34, with_name=True):
    """Dark branded background with logo and name (about dialog, installer art, DMG, stub background)."""
    img = gradient(w, h, C["navy"], C["navy_light"]).convert("RGBA")
    s = int(min(w, h) * logo_frac)
    ly = int(h * (0.16 if with_name else 0.33))
    img.alpha_composite(mark("app", s), ((w - s) // 2, ly))
    out = img.convert("RGB")
    if with_name:
        text_centered(out, NAME, ly + s + int(h * 0.05), max(12, int(min(w, h) * 0.085)))
    return out


def wiz_header(w, h, rtl=False):
    img = Image.new("RGBA", (w, h), (255, 255, 255, 255))
    s = h - 12
    x = 8 if rtl else w - s - 8
    img.alpha_composite(mark("app", s), (x, 6))
    return img.convert("RGB")


# ---------------------------------------------------------------- generic rendering
def is_tile(rel):
    r = rel.lower()
    return any(k in r for k in ("tile", "visualelements", "privatebrowsing_", "square150", "wide"))


def render_raster(rel, w, h):
    """Return a PIL image (RGBA or RGB) replacing the template image at relative path `rel`."""
    r = rel.lower()
    base = r.rsplit("/", 1)[-1]
    if base.startswith("wizheader"):
        return wiz_header(w, h, rtl="rtl" in base)
    if base.startswith("wizwatermark"):
        return splash(w, h, logo_frac=0.62)
    if base == "about.png":
        return splash(w, h, logo_frac=0.5)
    if base in ("background.png", "bgstub.jpg"):
        return splash(w, h, logo_frac=0.3)
    variant = classify(rel)
    if is_tile(rel):
        return tile(w, h, variant, scale=0.6 if w == h else 0.7)
    return tile(w, h, variant, scale=0.98)


# ---------------------------------------------------------------- file writers
def save_png(img, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)


def save_ico(path, variant, sizes):
    """Multi-resolution ICO; each size is rendered natively from the vector art (no blurry downscale)."""
    sizes = sorted(set(sizes))
    path.parent.mkdir(parents=True, exist_ok=True)
    big = max(sizes)
    imgs = [mark(variant, s) for s in sizes]
    base = imgs[sizes.index(big)]
    others = [im for s, im in zip(sizes, imgs) if s != big]
    base.save(path, format="ICO", sizes=[(s, s) for s in sizes], append_images=others)


def save_icns(path, variant):
    path.parent.mkdir(parents=True, exist_ok=True)
    mark(variant, 1024).save(path, format="ICNS")


def save_jpeg(img, path):
    img.convert("RGB").save(path, "JPEG", quality=90)


# ---------------------------------------------------------------- wordmark (text converted to outlines)
def wordmark_svg(text=None, viewbox=(372, 99), pad=4):
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont

    text = text or NAME
    font = TTFont(font_path())
    gs, cmap, hmtx = font.getGlyphSet(), font.getBestCmap(), font["hmtx"]
    upm = font["head"].unitsPerEm
    names = [cmap[ord(ch)] for ch in text]

    def layout(pen_for, scale, ox, oy):
        x = 0.0
        for g in names:
            gs[g].draw(pen_for(scale, ox + x * scale, oy))
            x += hmtx[g][0]

    def pass_pen(target):
        return lambda sc, tx, ty: TransformPen(target, (sc, 0, 0, -sc, tx, ty))

    s0 = 100 / upm
    bp = BoundsPen(gs)
    layout(pass_pen(bp), s0, 0, 0)
    x0, y0, x1, y1 = bp.bounds
    k = min((viewbox[0] - 2 * pad) / (x1 - x0), (viewbox[1] - 2 * pad) / (y1 - y0))
    s = s0 * k
    tx = (viewbox[0] - (x1 - x0) * k) / 2 - x0 * k
    ty = (viewbox[1] - (y1 - y0) * k) / 2 - y0 * k
    sp = SVGPathPen(gs)
    layout(pass_pen(sp), s, tx, ty)
    d = sp.getCommands()
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {viewbox[0]} {viewbox[1]}">'
            f'<path fill="context-fill" d="{d}"/></svg>\n')
