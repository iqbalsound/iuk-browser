"""Conflict-free merge of the synced document (format v2).

Document: {"v": 2, "kdf": ..., "bookmarks": {id: item}, "folders": {id: item}, "logins": {id: item}}

Bookmarks and folders merge *per field* (last write wins with a per-field timestamp), tags merge as an
add/remove set (each tag is its own last-write-wins register), so two devices editing different fields
of the same item never lose each other's change. Ties are broken deterministically, which makes the merge
commutative, associative and idempotent: every device converges to the same state whatever the sync order.

Folder-level conflicts are resolved when the tree is *viewed* (see `resolve`) and never by rewriting data:
  * items inside a folder that another device deleted are shown under the virtual "Recovered" folder,
  * if concurrent moves would create a cycle (A into B on one device, B into A on another) the folder with
    the smallest id is attached to "Other bookmarks".
Nothing is lost and no device has to write a "repair".
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

ROOT_PREFIX = "root:"
ROOT_TOOLBAR, ROOT_MENU, ROOT_UNFILED = "root:toolbar", "root:menu", "root:unfiled"
ROOTS = (ROOT_TOOLBAR, ROOT_MENU, ROOT_UNFILED)
RECOVERED = "root:recovered"
TOMBSTONE_MAX_AGE_MS = 90 * 24 * 3600 * 1000
DOC_VERSION = 2


def stable(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def bookmark_id(url: str) -> str:
    return "b:" + hashlib.sha1(url.encode()).hexdigest()[:20]


def folder_id_for_path(root: str, path: list[str]) -> str:
    return "f:" + hashlib.sha1((root + "/" + "/".join(path)).encode()).hexdigest()[:20]


def _pick(a: tuple, b: tuple) -> tuple:
    """a, b = (timestamp, value). Newest wins; on a tie the larger canonical value wins (deterministic)."""
    if a[0] != b[0]:
        return a if a[0] > b[0] else b
    return a if stable(a[1]) >= stable(b[1]) else b


def empty_doc() -> dict:
    return {"v": DOC_VERSION, "bookmarks": {}, "folders": {}, "logins": {}}


# ---------------------------------------------------------------- items
def merge_bookmark(a: dict | None, b: dict | None) -> dict | None:
    if a is None:
        return copy.deepcopy(b)
    if b is None:
        return copy.deepcopy(a)
    out = {"id": a["id"], "url": a["url"], "created": min(a.get("created", 0), b.get("created", 0))}
    out["titleTs"], out["title"] = _pick((a["titleTs"], a["title"]), (b["titleTs"], b["title"]))
    out["folderTs"], out["folder"] = _pick((a["folderTs"], a["folder"]), (b["folderTs"], b["folder"]))
    out["delTs"], out["deleted"] = _pick((a["delTs"], a["deleted"]), (b["delTs"], b["deleted"]))
    tags = {}
    for name in set(a.get("tags", {})) | set(b.get("tags", {})):
        ta, tb = a.get("tags", {}).get(name), b.get("tags", {}).get(name)
        if ta is None or tb is None:
            tags[name] = list(ta or tb)
        else:
            ts, on = _pick((ta[1], ta[0]), (tb[1], tb[0]))
            tags[name] = [on, ts]
    out["tags"] = tags
    return out


def merge_folder(a: dict | None, b: dict | None) -> dict | None:
    if a is None:
        return copy.deepcopy(b)
    if b is None:
        return copy.deepcopy(a)
    out = {"id": a["id"]}
    out["nameTs"], out["name"] = _pick((a["nameTs"], a["name"]), (b["nameTs"], b["name"]))
    out["parentTs"], out["parent"] = _pick((a["parentTs"], a["parent"]), (b["parentTs"], b["parent"]))
    out["delTs"], out["deleted"] = _pick((a["delTs"], a["deleted"]), (b["delTs"], b["deleted"]))
    return out


def merge_login(a: dict | None, b: dict | None) -> dict | None:
    """Whole-item last-write-wins. Equal timestamps: a deletion wins, then the canonical form decides."""
    if a is None:
        return copy.deepcopy(b)
    if b is None:
        return copy.deepcopy(a)
    if a["updatedAt"] != b["updatedAt"]:
        return copy.deepcopy(a if a["updatedAt"] > b["updatedAt"] else b)
    if bool(a.get("deleted")) != bool(b.get("deleted")):
        return copy.deepcopy(a if a.get("deleted") else b)
    return copy.deepcopy(a if stable(a) >= stable(b) else b)


def _merge_map(x: dict, y: dict, fn) -> dict:
    return {k: fn(x.get(k), y.get(k)) for k in set(x) | set(y)}


def merge_docs(a: dict, b: dict, now_ms: int | None = None) -> dict:
    out = {
        "v": DOC_VERSION,
        "bookmarks": _merge_map(a.get("bookmarks", {}), b.get("bookmarks", {}), merge_bookmark),
        "folders": _merge_map(a.get("folders", {}), b.get("folders", {}), merge_folder),
        "logins": _merge_map(a.get("logins", {}), b.get("logins", {}), merge_login),
    }
    if now_ms is not None:
        _gc(out, now_ms)
    return out


def _gc(doc: dict, now_ms: int) -> None:
    for k, it in list(doc["bookmarks"].items()):
        if it["deleted"] and now_ms - it["delTs"] > TOMBSTONE_MAX_AGE_MS:
            del doc["bookmarks"][k]
    for k, it in list(doc["folders"].items()):
        if it["deleted"] and now_ms - it["delTs"] > TOMBSTONE_MAX_AGE_MS:
            del doc["folders"][k]
    for k, it in list(doc["logins"].items()):
        if it.get("deleted") and now_ms - it["updatedAt"] > TOMBSTONE_MAX_AGE_MS:
            del doc["logins"][k]


def docs_equal(a: dict, b: dict) -> bool:
    return all(stable(a.get(ns, {})) == stable(b.get(ns, {})) for ns in ("bookmarks", "folders", "logins"))


# ---------------------------------------------------------------- tree view
def _find_cycle(parent: dict[str, str]) -> list[str] | None:
    for start in sorted(parent):
        seen: list[str] = []
        cur = start
        while cur in parent and not parent[cur].startswith(ROOT_PREFIX):
            if cur in seen:
                return seen[seen.index(cur):]
            seen.append(cur)
            cur = parent[cur]
    return None


def effective_parents(folders: dict) -> dict[str, str]:
    """Live folder id -> parent (a live folder id or a root id), with orphans recovered and cycles broken."""
    live = {k: f for k, f in folders.items() if not f["deleted"]}
    parent = {}
    for fid, f in live.items():
        p = f["parent"]
        parent[fid] = p if (p in live or p in ROOTS) else RECOVERED
    while True:
        cyc = _find_cycle(parent)
        if not cyc:
            return parent
        parent[min(cyc)] = ROOT_UNFILED


def effective_folder(item: dict, live_folders: set[str]) -> str:
    f = item["folder"]
    if f in ROOTS or f in live_folders:
        return f
    return RECOVERED


def resolve(doc: dict) -> dict:
    """Presentation tree: {root_id: {"folders": {fid: {...}}, "bookmarks": [...]}} (children via 'children')."""
    parent = effective_parents(doc.get("folders", {}))
    live = set(parent)
    nodes: dict[str, dict] = {r: {"id": r, "children": [], "bookmarks": []} for r in (*ROOTS, RECOVERED)}
    for fid in sorted(live, key=lambda i: (doc["folders"][i]["name"].lower(), i)):
        nodes[fid] = {"id": fid, "name": doc["folders"][fid]["name"], "children": [], "bookmarks": []}
    for fid in sorted(live, key=lambda i: (doc["folders"][i]["name"].lower(), i)):
        nodes[parent[fid]]["children"].append(nodes[fid])
    for it in sorted(doc.get("bookmarks", {}).values(), key=lambda i: (i["title"].lower(), i["id"])):
        if not it["deleted"]:
            nodes[effective_folder(it, live)]["bookmarks"].append(it)
    return nodes


# ---------------------------------------------------------------- v1 (extension 1.x) -> v2
def from_v1(doc: dict) -> dict:
    """Convert a v1 document (bookmarks keyed by URL with root + path) deterministically, so any two
    devices converting the same v1 document produce identical ids and timestamps."""
    out = empty_doc()
    out["logins"] = copy.deepcopy(doc.get("logins", {}))
    folder_ts: dict[str, int] = {}
    pending: list[tuple[str, dict, str]] = []
    for url, it in sorted(doc.get("bookmarks", {}).items()):
        bid = bookmark_id(it.get("url", url))
        ts = int(it.get("updatedAt", 0))
        if it.get("deleted"):
            out["bookmarks"][bid] = {"id": bid, "url": it.get("url", url), "title": "", "titleTs": 0, "folder": ROOT_UNFILED,
                                     "folderTs": 0, "tags": {}, "deleted": True, "delTs": ts, "created": ts}
            continue
        root = ROOT_PREFIX + (it.get("root") if it.get("root") in ("toolbar", "menu", "unfiled") else "unfiled")
        path = list(it.get("path") or [])
        parent = root
        for i, name in enumerate(path):
            fid = folder_id_for_path(root, path[: i + 1])
            folder_ts[fid] = max(folder_ts.get(fid, 0), ts)
            out["folders"].setdefault(fid, {"id": fid, "name": name, "parent": parent})
            parent = fid
        out["bookmarks"][bid] = {"id": bid, "url": it["url"], "title": it.get("title") or it["url"], "titleTs": ts,
                                 "folder": parent, "folderTs": ts, "tags": {}, "deleted": False, "delTs": 0, "created": ts}
    for fid, f in out["folders"].items():
        t = folder_ts[fid]
        f.update({"nameTs": t, "parentTs": t, "deleted": False, "delTs": 0})
    return out


def normalize(doc: dict) -> dict:
    """Accept a v1 or v2 document and return v2."""
    v = doc.get("v")
    if v == 1:
        return from_v1(doc)
    if v == DOC_VERSION:
        d = empty_doc()
        for ns in ("bookmarks", "folders", "logins"):
            d[ns] = copy.deepcopy(doc.get(ns, {}))
        return d
    raise ValueError(f"Unsupported sync data version {v!r}; update IUK Browser")
