/* Reads the live bookmark tree into a flat map keyed by URL, and applies merged changes back. */
var VFBookmarks = (function () {
  const ROOT_ID = { toolbar: 'toolbar_____', menu: 'menu________', unfiled: 'unfiled_____' };
  const ID_ROOT = { toolbar_____: 'toolbar', menu________: 'menu', unfiled_____: 'unfiled' };
  const SYNCABLE = /^(https?|ftp|file):/i;
  let quietUntil = 0;

  const isApplying = () => Date.now() < quietUntil;

  async function snapshotLocal() {
    const tree = await browser.bookmarks.getTree();
    const out = {};
    for (const r of tree[0].children || []) {
      const root = ID_ROOT[r.id];
      if (!root) continue; // skip "mobile" root
      (function walk(node, path) {
        for (const c of node.children || []) {
          if (c.type === 'folder') walk(c, path.concat(c.title));
          else if (c.type === 'bookmark' && SYNCABLE.test(c.url || '') && !out[c.url]) {
            out[c.url] = { url: c.url, title: c.title || c.url, root, path };
          }
        }
      })(r, []);
    }
    return out;
  }

  async function ensureFolder(rootId, path) {
    let parent = rootId;
    for (const name of path) {
      const kids = await browser.bookmarks.getChildren(parent);
      const hit = kids.find((k) => k.type === 'folder' && k.title === name);
      parent = hit ? hit.id : (await browser.bookmarks.create({ parentId: parent, title: name, type: 'folder' })).id;
    }
    return parent;
  }

  async function apply(merged, keys) {
    quietUntil = Date.now() + 3000;
    for (const k of keys) {
      const it = merged[k];
      const found = (await browser.bookmarks.search({ url: k })).filter((b) => b.url);
      if (it.deleted) { for (const b of found) await browser.bookmarks.remove(b.id); continue; }
      const parent = await ensureFolder(ROOT_ID[it.root] || ROOT_ID.unfiled, it.path || []);
      if (found.length) {
        const b = found[0];
        if (b.title !== it.title) await browser.bookmarks.update(b.id, { title: it.title });
        if (b.parentId !== parent) await browser.bookmarks.move(b.id, { parentId: parent });
      } else {
        await browser.bookmarks.create({ parentId: parent, title: it.title, url: k });
      }
    }
    quietUntil = Date.now() + 2000;
  }

  return { snapshotLocal, apply, isApplying };
})();
