#!/usr/bin/env python3
"""Create browser/branding/iuk-browser inside a Firefox source checkout.

Copies browser/branding/unofficial (so the file set always matches that Firefox version), then replaces
EVERY image in it with IUK Browser artwork at the same pixel size (app icons, taskbar/minimize icons, Windows
.ico, installer art, tiles, about dialog, private-browsing variants, document icons), rewrites the brand
strings, installer defines and colors, and points browser/confvars.sh at the new directory.

    python3 branding/apply_to_source.py /path/to/firefox-src
"""
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

import brand as B

NAME, SLUG, VENDOR = B.NAME, B.CFG["slug"], B.CFG["vendor"]
REPO = B.CFG["repo_url"]
NAVY = B.C["navy"]
MAC_ONLY = {"Assets.car", "dsstore"}  # compiled Apple asset catalog: cannot be generated here


def sub_define(text, key, value):
    return re.sub(rf'^(!define\s+{key}\s+).*$', lambda m: m.group(1) + value, text, flags=re.M)


def patch_text(dst):
    p = dst / "configure.sh"
    head = p.read_text().split("MOZ_APP_DISPLAYNAME")[0]
    p.write_text(head + f'MOZ_APP_DISPLAYNAME="{NAME}"\nMOZ_APP_REMOTINGNAME={SLUG}\nMOZ_MACBUNDLE_ID={B.CFG["bundle_id"]}\n')

    ftl = dst / "locales/en-US/brand.ftl"
    t = ftl.read_text()
    t = re.sub(r"^-brand-shorter-name = .*$", f"-brand-shorter-name = {NAME}", t, flags=re.M)
    t = re.sub(r"^-brand-short-name = .*$", f"-brand-short-name = {NAME}", t, flags=re.M)
    t = re.sub(r"^-brand-shortcut-name = .*$", f"-brand-shortcut-name = {NAME}", t, flags=re.M)
    t = re.sub(r"^-brand-full-name = .*$", f"-brand-full-name = {NAME}", t, flags=re.M)
    t = re.sub(r"^-brand-product-name = .*$", f"-brand-product-name = {NAME}", t, flags=re.M)
    t = re.sub(r"^-vendor-short-name = .*$", f"-vendor-short-name = {VENDOR}", t, flags=re.M)
    ftl.write_text(t)

    prop = dst / "locales/en-US/brand.properties"
    t = prop.read_text()
    for k in ("brandShorterName", "brandShortName", "brandFullName"):
        t = re.sub(rf"^{k}=.*$", f"{k}={NAME}", t, flags=re.M)
    prop.write_text(t)

    for f in dst.glob("*.VisualElementsManifest.xml"):
        f.write_text(re.sub(r"BackgroundColor='#[0-9a-fA-F]{6}'", f"BackgroundColor='{NAVY}'", f.read_text()))

    nsi = dst / "branding.nsi"
    t = nsi.read_text()
    t = sub_define(t, "BrandFullNameInternal", f'"{NAME}"')
    t = sub_define(t, "BrandFullName", f'"{NAME}"')
    t = sub_define(t, "CompanyName", f'"{VENDOR}"')
    t = sub_define(t, "URLInfoAbout", f'"{REPO}"')
    t = sub_define(t, "HelpLink", f'"{REPO}/issues"')
    for k in ("URLStubDownloadX86", "URLStubDownloadAMD64", "URLStubDownloadAArch64", "URLManualDownload"):
        t = sub_define(t, k, f'"{REPO}/releases/latest"')
    t = sub_define(t, "URLSystemRequirements", f'"{REPO}"')
    t = sub_define(t, "CertNameDownload", '""')
    t = sub_define(t, "CertIssuerDownload", '""')
    t = sub_define(t, "COMMON_BACKGROUND_COLOR", "0x" + NAVY.lstrip("#").upper())
    nsi.write_text(t)

    pref = dst / "pref/firefox-branding.js"
    pref.write_text(pref.read_text().replace("https://nightly.mozilla.org", REPO + "/releases"))

    css = dst / "content/aboutDialog.css"
    t = css.read_text().replace("#130829", NAVY).replace("hsla(235, 43%, 10%, 0.5)", "rgba(22, 41, 107, 0.5)")
    css.write_text(t)


def replace_images(dst):
    stats = {"png": 0, "ico": 0, "icns": 0, "bmp": 0, "jpg": 0, "svg": 0}
    skipped = []
    svg_map = {
        "content/about-logo.svg": (B.SRC / "logo.svg").read_text(),
        "content/document_pdf.svg": (B.SRC / "document_pdf.svg").read_text(),
        "content/about-wordmark.svg": B.wordmark_svg(),
        "content/firefox-wordmark.svg": B.wordmark_svg(),
    }
    for rel, content in svg_map.items():
        (dst / rel).write_text(content)
        stats["svg"] += 1

    for f in sorted(dst.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(dst).as_posix()
        ext = f.suffix.lower()
        if f.name in MAC_ONLY:
            skipped.append(rel)
            continue
        if ext == ".png":
            w, h = Image.open(f).size
            mode = Image.open(f).mode
            img = B.render_raster(rel, w, h)
            B.save_png(img if mode != "RGB" else img.convert("RGB"), f)
            stats["png"] += 1
        elif ext == ".ico":
            sizes = sorted({s[0] for s in Image.open(f).info.get("sizes", {(256, 256)})}) or [256]
            B.save_ico(f, B.classify(rel), sizes)
            stats["ico"] += 1
        elif ext == ".icns":
            B.save_icns(f, B.classify(rel))
            stats["icns"] += 1
        elif ext == ".bmp":
            w, h = Image.open(f).size
            B.render_raster(rel, w, h).convert("RGB").save(f, "BMP")
            stats["bmp"] += 1
        elif ext in (".jpg", ".jpeg"):
            w, h = Image.open(f).size
            B.save_jpeg(B.render_raster(rel, w, h), f)
            stats["jpg"] += 1
    return stats, skipped


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    src = Path(sys.argv[1]).resolve()
    tpl = src / "browser/branding/unofficial"
    dst = src / "browser/branding" / SLUG
    if not tpl.is_dir():
        raise SystemExit(f"{tpl} not found; pass the root of a Firefox source checkout")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(tpl, dst)
    patch_text(dst)
    stats, skipped = replace_images(dst)

    cv = src / "browser/confvars.sh"
    t = cv.read_text()
    cv.write_text(t.replace("MOZ_BRANDING_DIRECTORY=browser/branding/unofficial", f"MOZ_BRANDING_DIRECTORY=browser/branding/{SLUG}"))

    print(f"Created {dst}")
    print("Replaced:", ", ".join(f"{v} {k}" for k, v in stats.items() if v))
    if skipped:
        print("Left untouched (macOS-only, not built by this project):", ", ".join(skipped))
    def live_lines(p):  # ignore comments: the template's explanatory comments still say "Nightly"
        txt = p.read_text(errors="ignore")
        return "\n".join(l for l in txt.splitlines() if not l.lstrip().startswith(("#", "//", "/*", "*")))
    leftovers = [p.relative_to(dst).as_posix() for p in dst.rglob("*")
                 if p.is_file() and p.suffix in (".ftl", ".properties", ".nsi", ".sh", ".js", ".css", ".xml", ".svg")
                 and re.search(r"Nightly|Mozilla Developer Preview", live_lines(p))]
    if leftovers:
        print("WARNING: files still mentioning Nightly/Mozilla Developer Preview:", leftovers)


if __name__ == "__main__":
    main()
