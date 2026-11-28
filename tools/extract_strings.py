#!/usr/bin/env python3
"""Lists every translatable string: the first argument of tr(...) calls plus the theme names."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def strings_in(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.IfExp):
        yield from strings_in(node.body)
        yield from strings_in(node.orelse)


def extract() -> list[str]:
    found: set[str] = set()
    for p in (ROOT / "src" / "iuk_browser").rglob("*.py"):
        for n in ast.walk(ast.parse(p.read_text("utf-8"))):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "tr" and n.args:
                found.update(strings_in(n.args[0]))
    from iuk_browser.core.themes import THEMES
    found.update(t["name"] for t in THEMES)
    return sorted(found)


if __name__ == "__main__":
    keys = extract()
    print(len(keys), "strings", file=sys.stderr)
    for k in keys:
        print(k)
