#!/usr/bin/env python3
"""Hand translations to a native speaker and merge their corrections back, safely.

  python3 tools/review_translations.py export fr          # writes docs/translation-review/fr.csv
  # the reviewer edits ONLY the "corrected" column (leave it empty to accept the current text) and sends the file back
  python3 tools/review_translations.py import fr fr.csv   # validates {} placeholders, updates tools/translations.tsv,
                                                          # rebuilds the catalogs, and prints a summary
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_catalogs as MC  # noqa: E402

TSV = HERE / "translations.tsv"
OUT = HERE.parent / "docs" / "translation-review"


def export(lang: str, out: Path | None = None) -> Path:
    cat = MC.load()
    if lang not in cat:
        raise SystemExit(f"unknown language {lang!r}; choose one of {', '.join(MC.LANGS)}")
    out = out or OUT / f"{lang}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:      # utf-8-sig: opens correctly in Excel
        w = csv.writer(f)
        w.writerow(["english", "current", "corrected", "note"])
        for en in sorted(cat[lang]):
            w.writerow([en, cat[lang][en], "", "keep every {} exactly as in the English text" if "{}" in en else ""])
    return out


def import_review(lang: str, path: Path, tsv: Path = TSV) -> dict:
    col = 1 + MC.LANGS.index(lang)
    fixes: dict[str, str] = {}
    errors: list[str] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            en, new = row["english"], (row.get("corrected") or "").strip()
            if not new:
                continue
            if en.count("{}") != new.count("{}"):
                errors.append(f"placeholder count differs for {en!r}: {new!r}")
            elif " | " in new or "\n" in new:
                errors.append(f"remove ' | ' and line breaks from {new!r}")
            else:
                fixes[en] = new
    if errors:
        raise SystemExit("not imported:\n  " + "\n  ".join(errors))
    lines, changed, unknown = [], 0, set(fixes)
    for line in tsv.read_text("utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            parts = [p.strip() for p in line.split(" | ")]
            if parts[0] in fixes:
                unknown.discard(parts[0])
                if parts[col] != fixes[parts[0]]:
                    parts[col] = fixes[parts[0]]
                    changed += 1
                line = " | ".join(parts)
        lines.append(line)
    if unknown:
        raise SystemExit("these English strings are not in the table (was the file edited?): " + ", ".join(sorted(unknown)[:5]))
    tsv.write_text("\n".join(lines) + "\n", "utf-8")
    return {"changed": changed, "accepted": len(fixes)}


def main(argv) -> int:
    if len(argv) >= 3 and argv[1] == "export":
        print("wrote", export(argv[2]))
        return 0
    if len(argv) == 4 and argv[1] == "import":
        res = import_review(argv[2], Path(argv[3]))
        print(f"{res['changed']} translation(s) updated; rebuilding catalogs")
        return MC.main()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
