#!/usr/bin/env python3
"""Builds src/iuk_browser/i18n/<lang>.json from tools/translations.tsv and checks it against the code.

    python3 tools/make_catalogs.py          # write catalogs, fail on missing strings or broken placeholders
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from extract_strings import extract  # noqa: E402

LANGS = ["ur", "ar", "fr", "es", "de", "zh_CN"]
OUT = HERE.parent / "src" / "iuk_browser" / "i18n"


def load() -> dict[str, dict[str, str]]:
    cat = {l: {} for l in LANGS}
    for n, line in enumerate((HERE / "translations.tsv").read_text("utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(" | ")]
        if len(parts) != 1 + len(LANGS):
            raise SystemExit(f"translations.tsv line {n}: expected {1 + len(LANGS)} columns, got {len(parts)}: {line[:60]}")
        for lang, text in zip(LANGS, parts[1:]):
            cat[lang][parts[0]] = text
    return cat


def problems(cat) -> list[str]:
    keys, out = set(extract()), []
    for lang, d in cat.items():
        for k in sorted(keys - set(d)):
            out.append(f"[{lang}] missing: {k!r}")
        for k in sorted(set(d) - keys):
            out.append(f"[{lang}] unused: {k!r}")
        for k, v in d.items():
            if k in keys and k.count("{}") != v.count("{}"):
                out.append(f"[{lang}] placeholder mismatch: {k!r} -> {v!r}")
    return out


def main() -> int:
    cat = load()
    bad = problems(cat)
    OUT.mkdir(parents=True, exist_ok=True)
    for lang, d in cat.items():
        (OUT / f"{lang}.json").write_text(json.dumps(dict(sorted(d.items())), ensure_ascii=False, indent=1) + "\n", "utf-8")
    print(f"wrote {len(cat)} catalogs x {len(cat['ur'])} strings")
    for b in bad:
        print(b, file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
