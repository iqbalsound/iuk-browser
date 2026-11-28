"""Local bookmark store: folders, tags, tombstones, persistence, Netscape-HTML import/export."""
from __future__ import annotations

import functools
import html
import json
import threading
import time
import uuid
from html.parser import HTMLParser
from pathlib import Path

from . import merge as M


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        with self.lock:
            return fn(self, *a, **kw)
    return wrapper


class BookmarkStore:
    def __init__(self, path: Path | None = None, clock=None):
        self.path = Path(path) if path else None
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._last = 0
        self.bookmarks: dict[str, dict] = {}
        self.folders: dict[str, dict] = {}
        self.dirty = False
        self.lock = threading.RLock()      # shared with Account: the sync worker thread and the UI both touch this state
        if self.path and self.path.exists():
            self.load()

    # ---- infrastructure
    def _now(self) -> int:
        self._last = max(self._clock(), self._last + 1)   # strictly increasing: our edits never tie with themselves
        return self._last

    def _touch(self) -> None:
        self.dirty = True
        self.save()

    def load(self) -> None:
        d = json.loads(self.path.read_text("utf-8"))
        self.bookmarks, self.folders = d.get("bookmarks", {}), d.get("folders", {})

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"bookmarks": self.bookmarks, "folders": self.folders}, ensure_ascii=False), "utf-8")
            tmp.replace(self.path)

    @_locked
    def export_doc(self) -> dict:
        return {"bookmarks": self.bookmarks, "folders": self.folders}

    @_locked
    def replace(self, bookmarks: dict, folders: dict) -> None:
        self.bookmarks, self.folders = bookmarks, folders
        self.save()

    # ---- bookmarks
    @_locked
    def by_url(self, url: str) -> dict | None:
        it = self.bookmarks.get(M.bookmark_id(url))
        return None if not it or it["deleted"] else it

    @_locked
    def add_bookmark(self, url: str, title: str = "", folder: str = M.ROOT_TOOLBAR, tags=()) -> str:
        bid, t = M.bookmark_id(url), self._now()
        prev = self.bookmarks.get(bid)
        item = {"id": bid, "url": url, "title": title or url, "titleTs": t, "folder": folder, "folderTs": t,
                "tags": dict(prev["tags"]) if prev else {}, "deleted": False, "delTs": t,
                "created": prev["created"] if prev else t}
        self.bookmarks[bid] = item
        self._set_tags(item, set(tags), t)
        self._touch()
        return bid

    def _set_tags(self, item: dict, want: set[str], t: int) -> None:
        want = {x.strip().lower() for x in want if x.strip()}
        have = {n for n, (on, _) in item["tags"].items() if on}
        for n in want - have:
            item["tags"][n] = [True, t]
        for n in have - want:
            item["tags"][n] = [False, t]

    @_locked
    def update_bookmark(self, bid: str, title: str | None = None, folder: str | None = None, tags=None) -> None:
        it, t = self.bookmarks[bid], self._now()
        if title is not None and title != it["title"]:
            it["title"], it["titleTs"] = title, t
        if folder is not None and folder != it["folder"]:
            it["folder"], it["folderTs"] = folder, t
        if tags is not None:
            self._set_tags(it, set(tags), t)
        self._touch()

    @_locked
    def remove_bookmark(self, bid: str) -> None:
        it = self.bookmarks[bid]
        it["deleted"], it["delTs"] = True, self._now()
        self._touch()

    def tags_of(self, item: dict) -> list[str]:
        return sorted(n for n, (on, _) in item["tags"].items() if on)

    # ---- folders
    @_locked
    def add_folder(self, name: str, parent: str = M.ROOT_TOOLBAR) -> str:
        fid, t = "f:" + uuid.uuid4().hex[:20], self._now()
        self.folders[fid] = {"id": fid, "name": name, "nameTs": t, "parent": parent, "parentTs": t, "deleted": False, "delTs": t}
        self._touch()
        return fid

    @_locked
    def rename_folder(self, fid: str, name: str) -> None:
        f = self.folders[fid]
        f["name"], f["nameTs"] = name, self._now()
        self._touch()

    def _descendants(self, fid: str) -> set[str]:
        parent = M.effective_parents(self.folders)
        out, todo = set(), [fid]
        while todo:
            cur = todo.pop()
            for k, p in parent.items():
                if p == cur and k not in out:
                    out.add(k)
                    todo.append(k)
        return out

    @_locked
    def move_folder(self, fid: str, new_parent: str) -> None:
        if new_parent == fid or new_parent in self._descendants(fid):
            raise ValueError("A folder cannot be moved into itself")
        f = self.folders[fid]
        f["parent"], f["parentTs"] = new_parent, self._now()
        self._touch()

    @_locked
    def delete_folder(self, fid: str) -> None:
        """Deletes the folder with everything inside it (as seen in the effective tree)."""
        doomed = self._descendants(fid) | {fid}
        t = self._now()
        for k in doomed:
            self.folders[k]["deleted"], self.folders[k]["delTs"] = True, t
        for it in self.bookmarks.values():
            if not it["deleted"] and it["folder"] in doomed:
                it["deleted"], it["delTs"] = True, t
        self._touch()

    # ---- queries
    @_locked
    def view(self) -> dict:
        return M.resolve({"bookmarks": self.bookmarks, "folders": self.folders})

    @_locked
    def list(self, tag: str | None = None, text: str | None = None) -> list[dict]:
        out = []
        for it in self.bookmarks.values():
            if it["deleted"]:
                continue
            if tag and tag.lower() not in self.tags_of(it):
                continue
            if text and text.lower() not in (it["title"] + " " + it["url"]).lower():
                continue
            out.append(it)
        return sorted(out, key=lambda i: (i["title"].lower(), i["id"]))

    @_locked
    def all_tags(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for it in self.bookmarks.values():
            if not it["deleted"]:
                for n in self.tags_of(it):
                    counts[n] = counts.get(n, 0) + 1
        return dict(sorted(counts.items()))

    @_locked
    def folder_path(self, fid: str) -> list[str]:
        parent, names = M.effective_parents(self.folders), []
        while fid in parent:
            names.append(self.folders[fid]["name"])
            fid = parent[fid]
        return list(reversed(names))

    # ---- Netscape bookmarks HTML (every browser reads and writes this)
    @_locked
    def export_html(self) -> str:
        out = ["<!DOCTYPE NETSCAPE-Bookmark-file-1>", '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
               "<TITLE>Bookmarks</TITLE>", "<H1>Bookmarks</H1>", "<DL><p>"]

        def emit(node, depth):
            pad = "    " * depth
            for it in node["bookmarks"]:
                tags = ",".join(self.tags_of(it))
                out.append(f'{pad}<DT><A HREF="{html.escape(it["url"], True)}" ADD_DATE="{it["created"] // 1000}"'
                           + (f' TAGS="{html.escape(tags, True)}"' if tags else "") + f">{html.escape(it['title'])}</A>")
            for ch in node["children"]:
                out.append(f"{pad}<DT><H3>{html.escape(ch['name'])}</H3>")
                out.append(f"{pad}<DL><p>")
                emit(ch, depth + 1)
                out.append(f"{pad}</DL><p>")

        view = self.view()
        for rid, label in ((M.ROOT_TOOLBAR, "Bookmarks Toolbar"), (M.ROOT_MENU, "Bookmarks Menu"), (M.ROOT_UNFILED, "Other Bookmarks"), (M.RECOVERED, "Recovered")):
            n = view[rid]
            if n["children"] or n["bookmarks"]:
                out.append(f"    <DT><H3>{label}</H3>")
                out.append("    <DL><p>")
                emit(n, 2)
                out.append("    </DL><p>")
        out.append("</DL><p>")
        return "\n".join(out) + "\n"

    @_locked
    def import_html(self, text: str) -> int:
        store = self

        class P(HTMLParser):
            def __init__(self):
                super().__init__(convert_charrefs=True)
                self.stack: list[str] = [M.ROOT_UNFILED]
                self.mode = None
                self.attrs: dict = {}
                self.buf = ""
                self.pending_folder: str | None = None
                self.count = 0
                self.depth_names: list[str] = []

            def handle_starttag(self, tag, attrs):
                tag = tag.lower()
                if tag in ("h3", "a"):
                    self.mode, self.buf, self.attrs = tag, "", dict((k.lower(), v) for k, v in attrs)
                elif tag == "dl" and self.pending_folder is not None:
                    self.stack.append(self.pending_folder)
                    self.pending_folder = None

            def handle_data(self, data):
                if self.mode:
                    self.buf += data

            def handle_endtag(self, tag):
                tag = tag.lower()
                if tag == "h3" and self.mode == "h3":
                    name = self.buf.strip()
                    top = {"bookmarks toolbar": M.ROOT_TOOLBAR, "bookmarks menu": M.ROOT_MENU, "other bookmarks": M.ROOT_UNFILED}.get(name.lower())
                    self.pending_folder = top if (top and len(self.stack) == 1) else store.add_folder(name, self.stack[-1])
                    self.mode = None
                elif tag == "a" and self.mode == "a":
                    url = (self.attrs.get("href") or "").strip()
                    if url.lower().startswith(("http://", "https://", "ftp://", "file://")):
                        tags = [t for t in (self.attrs.get("tags") or "").split(",") if t.strip()]
                        store.add_bookmark(url, self.buf.strip() or url, self.stack[-1], tags)
                        self.count += 1
                    self.mode = None
                elif tag == "dl" and len(self.stack) > 1:
                    self.stack.pop()

        p = P()
        p.feed(text)
        return p.count
