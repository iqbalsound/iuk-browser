/* Test helpers: simulated browsers (mocked browser.* APIs) running the real background modules. */
const vm = require('node:vm'), fs = require('node:fs'), path = require('node:path');
const read = (f) => fs.readFileSync(path.join(__dirname, '../extension', f), 'utf8');

function makeBrowser() {
  const store = {}; let n = 0;
  const nodes = {};
  const add = (o) => { nodes[o.id] = o; if (o.parentId) nodes[o.parentId].children.push(o); return o; };
  const root = add({ id: 'root________', type: 'folder', title: '', children: [] });
  for (const id of ['toolbar_____', 'menu________', 'unfiled_____', 'mobile______']) add({ id, type: 'folder', title: id, parentId: root.id, children: [] });
  const strip = (x) => Object.assign({}, x, { children: x.children && x.children.map(strip) });
  return {
    store, nodes,
    browser: {
      storage: { local: {
        get: async (k) => { const r = {}; for (const key of [].concat(k)) if (key in store) r[key] = JSON.parse(JSON.stringify(store[key])); return r; },
        set: async (o) => { for (const [k, v] of Object.entries(o)) store[k] = JSON.parse(JSON.stringify(v)); },
        remove: async (k) => { for (const key of [].concat(k)) delete store[key]; },
      } },
      bookmarks: {
        getTree: async () => [strip(root)],
        getChildren: async (id) => nodes[id].children.map((c) => Object.assign({}, c, { children: undefined })),
        create: async ({ parentId, title, url, type }) => add({ id: 'n' + (++n), parentId, title, url, type: url ? 'bookmark' : 'folder', children: url ? undefined : [] }),
        search: async ({ url }) => Object.values(nodes).filter((x) => x.url === url),
        update: async (id, ch) => Object.assign(nodes[id], ch),
        move: async (id, { parentId }) => { const o = nodes[id]; nodes[o.parentId].children = nodes[o.parentId].children.filter((c) => c !== o); o.parentId = parentId; nodes[parentId].children.push(o); },
        remove: async (id) => { const o = nodes[id]; nodes[o.parentId].children = nodes[o.parentId].children.filter((c) => c !== o); delete nodes[id]; },
      },
    },
  };
}

function device() {
  const m = makeBrowser();
  const ctx = vm.createContext({ browser: m.browser, fetch, crypto: globalThis.crypto, TextEncoder, TextDecoder, btoa, atob, URL, console });
  for (const f of ['vendor/argon2.umd.min.js', 'shared/common.js', 'background/crypto.js', 'background/merge.js', 'background/bookmarks.js', 'background/core.js']) vm.runInContext(read(f), ctx, { filename: f });
  // cheap KDF parameters so tests are fast (production values are covered by a known-answer test)
  vm.runInContext("VFCrypto.PARAMS['argon2id-v2'] = { memoryKiB: 256, passes: 1, lanes: 1 }; VFCrypto.PARAMS['pbkdf2-v1'].iterations = 1000;", ctx);
  const core = vm.runInContext('VFCore', ctx), cx = vm.runInContext('VFCrypto', ctx), common = vm.runInContext('VFCommon', ctx);
  const bm = (parentId, title, url) => m.browser.bookmarks.create({ parentId, title, url });
  const urls = () => Object.values(m.nodes).filter((x) => x.url).map((x) => x.url).sort();
  return { core, cx, common, m, bm, urls, ctx };
}


module.exports = { makeBrowser, device, read };
