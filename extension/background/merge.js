/* Per-item last-write-wins merge with tombstones. Pure functions (unit-tested in Node). */
var VFMerge = (function () {
  const TOMBSTONE_MAX_AGE = 90 * 24 * 3600 * 1000;

  function stable(v) {
    if (Array.isArray(v)) return '[' + v.map(stable).join(',') + ']';
    if (v && typeof v === 'object') return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + stable(v[k])).join(',') + '}';
    return JSON.stringify(v);
  }
  const same = (a, b) => stable(a) === stable(b);

  function mergeMaps(local, remote) {
    local = local || {}; remote = remote || {};
    const merged = {}, changedLocal = []; let changedRemote = false;
    for (const k of new Set([...Object.keys(local), ...Object.keys(remote)])) {
      const l = local[k], r = remote[k]; let w;
      if (!l) w = r;
      else if (!r) w = l;
      else if (r.updatedAt > l.updatedAt) w = r;
      else if (l.updatedAt > r.updatedAt) w = l;
      else w = (r.deleted && !l.deleted) ? r : l; // tie: deletion wins
      merged[k] = w;
      if (!same(w, l)) changedLocal.push(k);
      if (!same(w, r)) changedRemote = true;
    }
    return { merged, changedLocal, changedRemote };
  }

  function gc(map, now) {
    let removed = false;
    for (const k of Object.keys(map)) if (map[k].deleted && now - map[k].updatedAt > TOMBSTONE_MAX_AGE) { delete map[k]; removed = true; }
    return removed;
  }

  function mergeDocs(localDoc, remoteDoc, now) {
    const out = { v: 1 }, changed = {}; let pushNeeded = !remoteDoc;
    for (const ns of ['bookmarks', 'logins']) {
      const m = mergeMaps(localDoc[ns], remoteDoc && remoteDoc[ns]);
      if (gc(m.merged, now)) pushNeeded = true;
      out[ns] = m.merged; changed[ns] = m.changedLocal.filter((k) => m.merged[k]);
      if (m.changedRemote) pushNeeded = true;
    }
    return { doc: out, changed, pushNeeded };
  }

  // Turns a snapshot of the live bookmark tree into versioned state: bumps updatedAt only for new/changed
  // items and writes tombstones for items that disappeared since `prev`.
  function reconcileLocal(prev, current, now) {
    prev = prev || {}; const out = {};
    const sig = (i) => stable([i.title, i.root, i.path]);
    for (const [k, c] of Object.entries(current)) {
      const p = prev[k];
      if (p && !p.deleted && sig(p) === sig(c)) out[k] = p;
      else out[k] = { url: c.url, title: c.title, root: c.root, path: c.path, updatedAt: now, deleted: false };
    }
    for (const [k, p] of Object.entries(prev)) {
      if (out[k]) continue;
      out[k] = p.deleted ? p : { url: p.url, deleted: true, updatedAt: now };
    }
    return out;
  }

  return { mergeMaps, mergeDocs, reconcileLocal, stable };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = VFMerge;
