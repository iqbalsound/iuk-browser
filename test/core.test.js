const test = require('node:test'), assert = require('node:assert/strict');
const os = require('node:os'), fs = require('node:fs'), path = require('node:path');
const C = require('../extension/background/crypto.js');
const M = require('../extension/background/merge.js');
const V = require('../extension/shared/common.js');
const { createServer } = require('../server/server.js');

const DEFAULTS = JSON.parse(JSON.stringify(C.PARAMS));
C.PARAMS['argon2id-v2'] = { memoryKiB: 256, passes: 1, lanes: 1 };
C.PARAMS['pbkdf2-v1'].iterations = 1000;

test('same user+secret derives same key/token; different secret does not (both KDFs)', async () => {
  for (const kdf of [C.KDF_LEGACY, C.KDF_LATEST]) {
    const a = await C.deriveKeys('Me@X.com', 'correct horse battery', kdf);
    const b = await C.deriveKeys(' me@x.com ', 'correct horse battery', kdf);
    const c = await C.deriveKeys('me@x.com', 'wrong horse battery!!', kdf);
    assert.equal(a.token, b.token); assert.notEqual(a.token, c.token); assert.equal(a.token.length, 64);
    const blob = await C.encrypt(a.key, { hello: 'wörld' });
    assert.deepEqual(await C.decrypt(b.key, blob), { hello: 'wörld' });
    await assert.rejects(() => C.decrypt(c.key, blob));
    await assert.rejects(() => C.decrypt(a.key, blob.slice(0, -4) + 'AAAA'));
  }
});

test('PBKDF2 and Argon2id vaults never collide on the server token', async () => {
  const a = await C.deriveKeys('me@x.com', 'same-secret-for-both', C.KDF_LEGACY);
  const b = await C.deriveKeys('me@x.com', 'same-secret-for-both', C.KDF_LATEST);
  assert.notEqual(a.token, b.token);
  await assert.rejects(() => C.deriveKeys('me@x.com', 'x', 'md5-v0'), /Unknown key derivation/);
});

test('known answer: production Argon2id parameters are frozen', async () => {
  const saved = C.PARAMS['argon2id-v2'];
  C.PARAMS['argon2id-v2'] = DEFAULTS['argon2id-v2'];
  try {
    assert.deepEqual(DEFAULTS['argon2id-v2'], { memoryKiB: 65536, passes: 3, lanes: 1 });
    const { token } = await C.deriveKeys('me@x.com', 'correct horse battery staple', C.KDF_LATEST);
    assert.equal(token, '5f0dac10d64f3e189dcb1df547cd32ddd7bcc834d51ae789cffac5f7eb21be0b');
  } finally { C.PARAMS['argon2id-v2'] = saved; }
});

test('merge: newest wins, tombstone beats older edit, new items unioned', () => {
  const l = { a: { updatedAt: 5, v: 'L' }, b: { updatedAt: 9, deleted: true }, c: { updatedAt: 1 } };
  const r = { a: { updatedAt: 7, v: 'R' }, b: { updatedAt: 3, v: 'old' }, d: { updatedAt: 2 } };
  const { merged, changedLocal, changedRemote } = M.mergeMaps(l, r);
  assert.equal(merged.a.v, 'R'); assert.equal(merged.b.deleted, true);
  assert.ok(merged.c && merged.d);
  assert.deepEqual(changedLocal.sort(), ['a', 'd']); assert.equal(changedRemote, true);
  const again = M.mergeMaps(merged, merged); assert.equal(again.changedRemote, false); assert.equal(again.changedLocal.length, 0);
});

test('merge: old tombstones are garbage-collected', () => {
  const now = Date.now(), old = now - 100 * 86400000;
  const r = M.mergeDocs({ bookmarks: { x: { deleted: true, updatedAt: old } }, logins: {} }, { v: 1, bookmarks: {}, logins: {} }, now);
  assert.equal(r.doc.bookmarks.x, undefined);
});

test('reconcileLocal: new, unchanged, moved and deleted bookmarks', () => {
  const bm = (t, p) => ({ url: 'https://a', title: t, root: 'toolbar', path: p });
  const s1 = M.reconcileLocal({}, { 'https://a': bm('A', []) }, 100);
  assert.equal(s1['https://a'].updatedAt, 100);
  const s2 = M.reconcileLocal(s1, { 'https://a': bm('A', []) }, 200);
  assert.equal(s2['https://a'].updatedAt, 100);
  const s3 = M.reconcileLocal(s2, { 'https://a': bm('A2', ['f']) }, 300);
  assert.equal(s3['https://a'].updatedAt, 300);
  const s4 = M.reconcileLocal(s3, {}, 400);
  assert.deepEqual(s4['https://a'], { url: 'https://a', deleted: true, updatedAt: 400 });
  assert.equal(M.reconcileLocal(s4, {}, 500)['https://a'].updatedAt, 400);
});

test('color invert CSS, themes, hosts, csv, generator', () => {
  assert.equal(V.displayCSS({ mode: 'off' }, 'x.com'), '');
  assert.match(V.displayCSS({ mode: 'all' }, 'x.com'), /invert\(1\) hue-rotate\(180deg\)/);
  assert.match(V.displayCSS({ mode: 'sites', sites: ['x.com'] }, 'x.com'), /invert/);
  assert.equal(V.displayCSS({ mode: 'sites', sites: ['y.com'] }, 'x.com'), '');
  assert.match(V.displayCSS({ mode: 'off', sepia: 40 }, 'x.com'), /sepia\(40%\)/);
  const t = V.makeTheme('#1c1b22', '#fbfbfe', '#00ddff');
  assert.equal(t.properties.color_scheme, 'dark'); assert.match(t.colors.toolbar, /^#[0-9a-f]{6}$/);
  assert.equal(V.makeTheme('#fdf6e3', '#586e75', '#268bd2').properties.color_scheme, 'light');
  assert.ok(V.hostMatches('example.com', 'login.example.com')); assert.ok(!V.hostMatches('example.com', 'evilexample.com'));
  assert.equal(V.hostFrom('https://www.Example.com/a?b'), 'example.com');
  const rows = V.parseCSV('url,username,password\r\n"https://a.com","u,1","p""w"\r\n');
  assert.deepEqual(V.loginsFromCSV(rows), [{ host: 'a.com', username: 'u,1', password: 'p"w', notes: '' }]);
  assert.equal(V.parseCSV(V.toCSV([['a', 'b"c']]))[0][1], 'b"c');
  for (let i = 0; i < 50; i++) assert.match(V.genPassword(20), /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{20}$/);
});

test('relay server + two devices converge (end to end)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vf-'));
  const srv = createServer({ dataDir: dir }); await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const base = 'http://127.0.0.1:' + srv.address().port;
  const dev = async () => C.deriveKeys('me@x.com', 'a-long-shared-secret');
  const A = await dev(), B = await dev(), bad = await C.deriveKeys('me@x.com', 'another-secret-xx');
  const H = (t, x) => ({ headers: { Authorization: 'Bearer ' + t, ...x } });
  assert.equal((await fetch(base + '/v1/blob', H(A.token))).status, 404);
  assert.equal((await fetch(base + '/v1/blob', { headers: {} })).status, 401);
  // device A pushes
  const docA = { v: 1, bookmarks: { u1: { updatedAt: 1, url: 'u1' } }, logins: { 'a.com|me': { id: 'a.com|me', password: 'pw1', updatedAt: 1 } } };
  let put = await fetch(base + '/v1/blob', { method: 'PUT', body: await C.encrypt(A.key, docA), ...H(A.token, { 'If-None-Match': '*' }) });
  assert.equal(put.status, 200);
  assert.equal((await fetch(base + '/v1/blob', { method: 'PUT', body: await C.encrypt(A.key, docA), ...H(A.token, { 'If-None-Match': '*' }) })).status, 412);
  // device B pulls, merges its own item, pushes with etag
  const got = await fetch(base + '/v1/blob', H(B.token)); const etag = got.headers.get('ETag');
  const remote = await C.decrypt(B.key, await got.text());
  const m = M.mergeDocs({ v: 1, bookmarks: { u2: { updatedAt: 2, url: 'u2' } }, logins: {} }, remote, 10);
  assert.deepEqual(Object.keys(m.doc.bookmarks).sort(), ['u1', 'u2']); assert.equal(m.doc.logins['a.com|me'].password, 'pw1');
  put = await fetch(base + '/v1/blob', { method: 'PUT', body: await C.encrypt(B.key, m.doc), ...H(B.token, { 'If-Match': etag }) });
  assert.equal(put.status, 200);
  assert.equal((await fetch(base + '/v1/blob', { method: 'PUT', body: await C.encrypt(B.key, m.doc), ...H(B.token, { 'If-Match': etag }) })).status, 412);
  // stored data is ciphertext only; a different secret cannot read it
  const stored = fs.readdirSync(dir).map((f) => fs.readFileSync(path.join(dir, f), 'utf8')).join('');
  assert.ok(!stored.includes('pw1') && !stored.includes('a.com'));
  assert.equal((await fetch(base + '/v1/blob', H(bad.token))).status, 404);
  const fresh = (await fetch(base + '/v1/blob', H(A.token))).headers.get('ETag');
  assert.equal((await fetch(base + '/v1/blob', { method: 'PUT', body: 'not encrypted', ...H(A.token, { 'If-Match': fresh }) })).status, 400);
  srv.closeAllConnections(); srv.close();
});

test('pairing code round trip and validation', () => {
  const code = V.encodePairing({ u: 'me@x.com', k: 'abcdefghijklmnopqrstuvwxyz123456', s: 'https://sync.example.com/' });
  assert.ok(code.startsWith('IUKB1:')); assert.match(code, /^IUKB1:[A-Za-z0-9_-]+$/);
  assert.deepEqual(V.decodePairing(' ' + code + '\n'), { username: 'me@x.com', secret: 'abcdefghijklmnopqrstuvwxyz123456', server: 'https://sync.example.com' });
  assert.equal(V.decodePairing(V.encodePairing({ u: 'ü@x.com', k: 'k'.repeat(12) })).username, 'ü@x.com');
  assert.throws(() => V.decodePairing('hello'), /not an IUK Browser pairing code/);
  assert.throws(() => V.decodePairing('IUKB1:%%%'), /damaged/);
  assert.throws(() => V.decodePairing(V.encodePairing({ u: 'a', k: 'short' })), /incomplete/);
  assert.throws(() => V.decodePairing(V.encodePairing({ u: 'a@b.c', k: 'k'.repeat(12), s: 'javascript:alert(1)' })), /invalid server/);
});

test('server: DELETE removes only the caller\'s blob', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vfd-'));
  const srv = createServer({ dataDir: dir }); await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const base = 'http://127.0.0.1:' + srv.address().port;
  const A = await C.deriveKeys('a@x.com', 'secret-number-one'), B = await C.deriveKeys('b@x.com', 'secret-number-two');
  const put = async (k) => fetch(base + '/v1/blob', { method: 'PUT', body: await C.encrypt(k.key, { v: 1 }), headers: { Authorization: 'Bearer ' + k.token, 'If-None-Match': '*' } });
  assert.equal((await put(A)).status, 200); assert.equal((await put(B)).status, 200);
  assert.equal((await fetch(base + '/v1/blob', { method: 'DELETE', headers: { Authorization: 'Bearer ' + A.token } })).status, 200);
  assert.equal((await fetch(base + '/v1/blob', { headers: { Authorization: 'Bearer ' + A.token } })).status, 404);
  assert.equal((await fetch(base + '/v1/blob', { headers: { Authorization: 'Bearer ' + B.token } })).status, 200);
  assert.equal((await fetch(base + '/v1/blob', { method: 'DELETE' })).status, 401);
  srv.closeAllConnections(); srv.close();
});
