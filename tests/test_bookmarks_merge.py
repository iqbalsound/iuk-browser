import copy
import random

import pytest

from iuk_browser.core import merge as M
from iuk_browser.core.bookmarks import BookmarkStore


class Clock:
    def __init__(self):
        self.t = 1_000_000

    def __call__(self):
        self.t += 1
        return self.t


def replicas(n=2):
    c = Clock()
    return c, [BookmarkStore(clock=c) for _ in range(n)]


def sync(a: BookmarkStore, b: BookmarkStore):
    m = M.merge_docs(a.export_doc(), b.export_doc())
    for s in (a, b):
        s.replace(copy.deepcopy(m["bookmarks"]), copy.deepcopy(m["folders"]))


def view_ids(store):
    v = store.view()
    return {r: sorted(b["title"] for b in n["bookmarks"]) for r, n in v.items()}


def test_field_level_merge_keeps_both_edits():
    c, (a, b) = replicas()
    bid = a.add_bookmark("https://x.example/", "X", tags=["news"])
    sync(a, b)
    f = a.add_folder("Reading")
    sync(a, b)
    a.update_bookmark(bid, title="X renamed")               # device A edits the title
    b.update_bookmark(bid, folder=f, tags=["news", "tech"])   # device B moves it and adds a tag
    sync(a, b)
    for s in (a, b):
        it = s.bookmarks[bid]
        assert it["title"] == "X renamed" and it["folder"] == f
        assert s.tags_of(it) == ["news", "tech"]


def test_tag_add_remove_is_last_write_wins_per_tag():
    c, (a, b) = replicas()
    bid = a.add_bookmark("https://t.example/", "T", tags=["a", "b"])
    sync(a, b)
    a.update_bookmark(bid, tags=["a"])                 # A removes "b" ...
    b.update_bookmark(bid, tags=["a", "b", "c"])       # ... B only adds "c" and never touches "b"
    sync(a, b)
    assert a.tags_of(a.bookmarks[bid]) == ["a", "c"] == b.tags_of(b.bookmarks[bid])   # the removal stands
    b.update_bookmark(bid, tags=["a", "c", "b"])       # B deliberately adds "b" again, later than the removal
    sync(a, b)
    assert a.tags_of(a.bookmarks[bid]) == ["a", "b", "c"] == b.tags_of(b.bookmarks[bid])


def test_delete_folder_vs_concurrent_add_goes_to_recovered_not_lost():
    c, (a, b) = replicas()
    f = a.add_folder("Projects")
    a.add_bookmark("https://old.example/", "Old", folder=f)
    sync(a, b)
    a.delete_folder(f)                                     # A deletes the folder and its contents
    b.add_bookmark("https://new.example/", "New", folder=f)   # B adds into it at the same time
    sync(a, b)
    for s in (a, b):
        v = s.view()
        assert [x["title"] for x in v[M.RECOVERED]["bookmarks"]] == ["New"]
        assert s.by_url("https://old.example/") is None
        assert M.ROOT_TOOLBAR in v and not v[M.ROOT_TOOLBAR]["children"]


def test_concurrent_folder_moves_cannot_create_a_cycle():
    c, (a, b) = replicas()
    f1, f2 = a.add_folder("One"), a.add_folder("Two")
    a.add_bookmark("https://1.example/", "in1", folder=f1)
    a.add_bookmark("https://2.example/", "in2", folder=f2)
    sync(a, b)
    a.move_folder(f1, f2)       # A: One goes into Two
    b.move_folder(f2, f1)       # B: Two goes into One
    sync(a, b)
    for s in (a, b):
        parents = M.effective_parents(s.folders)
        assert M._find_cycle(parents) is None
        v = s.view()
        titles = []

        def walk(n):
            titles.extend(x["title"] for x in n["bookmarks"])
            for ch in n["children"]:
                walk(ch)
        for r in (M.ROOT_TOOLBAR, M.ROOT_MENU, M.ROOT_UNFILED, M.RECOVERED):
            walk(v[r])
        assert sorted(titles) == ["in1", "in2"]


def test_local_move_into_own_descendant_is_rejected():
    c, (a,) = replicas(1)
    f1 = a.add_folder("A"); f2 = a.add_folder("B", f1)
    with pytest.raises(ValueError):
        a.move_folder(f1, f2)
    with pytest.raises(ValueError):
        a.move_folder(f1, f1)


def test_re_adding_a_deleted_bookmark_revives_it_and_keeps_history():
    c, (a, b) = replicas()
    bid = a.add_bookmark("https://r.example/", "R", tags=["x"])
    sync(a, b)
    b.remove_bookmark(bid); sync(a, b)
    assert a.by_url("https://r.example/") is None
    a.add_bookmark("https://r.example/", "R again", tags=["y"]); sync(a, b)
    it = b.by_url("https://r.example/")
    assert it["title"] == "R again" and b.tags_of(it) == ["y"]


def test_random_operations_converge_and_never_lose_data():
    rnd = random.Random(1234)
    for round_ in range(15):
        c, reps = replicas(3)
        urls = [f"https://site{i}.example/" for i in range(8)]
        for _ in range(120):
            s = rnd.choice(reps)
            op = rnd.randrange(9)
            folders = [k for k, f in s.folders.items() if not f["deleted"]]
            try:
                if op == 0:
                    s.add_bookmark(rnd.choice(urls), f"t{rnd.randrange(50)}", rnd.choice([M.ROOT_TOOLBAR, M.ROOT_UNFILED] + folders), rnd.sample(["a", "b", "c"], rnd.randrange(3)))
                elif op == 1 and s.bookmarks:
                    s.update_bookmark(rnd.choice(list(s.bookmarks)), title=f"n{rnd.randrange(50)}")
                elif op == 2 and s.bookmarks and folders:
                    s.update_bookmark(rnd.choice(list(s.bookmarks)), folder=rnd.choice(folders))
                elif op == 3 and s.bookmarks:
                    s.update_bookmark(rnd.choice(list(s.bookmarks)), tags=rnd.sample(["a", "b", "c"], rnd.randrange(4)))
                elif op == 4 and s.bookmarks:
                    s.remove_bookmark(rnd.choice(list(s.bookmarks)))
                elif op == 5:
                    s.add_folder(f"F{rnd.randrange(9)}", rnd.choice([M.ROOT_TOOLBAR] + folders))
                elif op == 6 and folders:
                    s.rename_folder(rnd.choice(folders), f"R{rnd.randrange(9)}")
                elif op == 7 and len(folders) > 1:
                    s.move_folder(rnd.choice(folders), rnd.choice(folders + [M.ROOT_MENU]))
                elif op == 8 and folders and rnd.random() < 0.3:
                    s.delete_folder(rnd.choice(folders))
            except ValueError:
                pass
            if rnd.random() < 0.15:
                sync(*rnd.sample(reps, 2))
        for _ in range(2):                      # final full mesh, twice, in random order
            for a in rnd.sample(reps, 3):
                for b in rnd.sample(reps, 3):
                    if a is not b:
                        sync(a, b)
        base = reps[0]
        for r in reps[1:]:
            assert M.docs_equal(base.export_doc(), r.export_doc())
        assert M._find_cycle(M.effective_parents(base.folders)) is None
        # every live bookmark is displayed exactly once
        shown = []
        def walk(n):
            shown.extend(b["id"] for b in n["bookmarks"])
            for ch in n["children"]:
                walk(ch)
        for n in base.view().values():
            walk(n) if n["id"].startswith("root:") else None
        live = sorted(k for k, v in base.bookmarks.items() if not v["deleted"])
        assert sorted(shown) == live


def test_merge_is_idempotent_and_commutative():
    c, (a, b) = replicas()
    a.add_bookmark("https://i.example/", "I", tags=["z"]); b.add_bookmark("https://j.example/", "J")
    ab = M.merge_docs(a.export_doc(), b.export_doc()); ba = M.merge_docs(b.export_doc(), a.export_doc())
    assert M.docs_equal(ab, ba)
    assert M.docs_equal(ab, M.merge_docs(ab, ab))


def test_tombstones_are_garbage_collected_after_90_days():
    now = 10 ** 13
    old = now - M.TOMBSTONE_MAX_AGE_MS - 1
    doc = {"bookmarks": {"b:1": {"id": "b:1", "url": "u", "title": "", "titleTs": 0, "folder": M.ROOT_UNFILED, "folderTs": 0,
                                  "tags": {}, "deleted": True, "delTs": old, "created": 0}}, "folders": {}, "logins": {}}
    assert M.merge_docs(doc, M.empty_doc(), now)["bookmarks"] == {}
    assert M.merge_docs(doc, M.empty_doc())["bookmarks"] != {}


def test_v1_document_conversion_is_deterministic_and_merges():
    v1 = {"v": 1, "bookmarks": {
        "https://a.example/": {"url": "https://a.example/", "title": "A", "root": "toolbar", "path": ["News", "Tech"], "updatedAt": 50, "deleted": False},
        "https://b.example/": {"url": "https://b.example/", "title": "B", "root": "toolbar", "path": ["News"], "updatedAt": 60, "deleted": False},
        "https://c.example/": {"url": "https://c.example/", "deleted": True, "updatedAt": 70}},
        "logins": {"a.com|me": {"id": "a.com|me", "host": "a.com", "username": "me", "password": "p", "notes": "", "createdAt": 1, "updatedAt": 2, "deleted": False}}}
    d1, d2 = M.normalize(v1), M.normalize(copy.deepcopy(v1))
    assert M.docs_equal(d1, d2)
    s = BookmarkStore()
    s.replace(d1["bookmarks"], d1["folders"])
    v = s.view()
    news = v[M.ROOT_TOOLBAR]["children"][0]
    assert news["name"] == "News" and news["children"][0]["name"] == "Tech"
    assert [b["title"] for b in news["bookmarks"]] == ["B"] and [b["title"] for b in news["children"][0]["bookmarks"]] == ["A"]
    assert s.by_url("https://c.example/") is None and d1["logins"]["a.com|me"]["password"] == "p"
    with pytest.raises(ValueError):
        M.normalize({"v": 3})


def test_html_import_export_round_trip_with_folders_and_tags(tmp_path):
    c, (a, b) = replicas()
    f = a.add_folder("Dev"); g = a.add_folder("Python", f)
    a.add_bookmark("https://py.example/?q=1&r=2", "Py & <Co>", folder=g, tags=["lang", "docs"])
    a.add_bookmark("https://top.example/", "Top")
    html_text = a.export_html()
    n = b.import_html(html_text)
    assert n == 2
    it = b.by_url("https://py.example/?q=1&r=2")
    assert it["title"] == "Py & <Co>" and b.tags_of(it) == ["docs", "lang"]
    assert b.folder_path(it["folder"]) == ["Dev", "Python"]
    assert b.by_url("https://top.example/") is not None


def test_store_persists_to_disk(tmp_path):
    p = tmp_path / "b.json"
    a = BookmarkStore(p); bid = a.add_bookmark("https://p.example/", "P", tags=["k"])
    b = BookmarkStore(p)
    assert b.bookmarks[bid]["title"] == "P" and b.tags_of(b.bookmarks[bid]) == ["k"]
