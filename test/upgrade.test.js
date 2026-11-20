/* v1.0 -> v1.1: an existing PBKDF2 vault (local + server copy) must migrate to Argon2id without data loss. */
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const { createServer } = require('../server/server.js');
const { device } = require('./helpers.js');

const SECRET = 'my-secret-connect-key', USER = 'me@x.com';
const login = (id, host, username, password, t) => ({ id, host, username, password, notes: '', createdAt: t, updatedAt: t, deleted: false });

async function startServer() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vfu-'));
  const srv = createServer({ dataDir: dir }); await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  return { srv, dir, base: 'http://127.0.0.1:' + srv.address().port };
}
const stop = (srv) => { srv.closeAllConnections(); srv.close(); };

/** Writes the storage a v1.0 install would have, plus a PBKDF2 server copy. */
async function legacyInstall(d, server, withRemote) {
  const old = await d.cx.deriveKeys(USER, SECRET, 'pbkdf2-v1');
  await d.m.browser.storage.local.set({
    vf_setup: { username: USER, verifier: await d.cx.encrypt(old.key, { ok: 'iuk-browser' }) },   // no kdf field = legacy
    vf_server: server, vf_bm_prev: {},
    vf_logins_enc: await d.cx.encrypt(old.key, { 'a.com|me': login('a.com|me', 'a.com', 'me', 'local-pw', 5) }),
  });
  if (withRemote) {
    const doc = { v: 1,
      bookmarks: { 'https://r.example/': { url: 'https://r.example/', title: 'Remote', root: 'toolbar', path: ['News'], updatedAt: 1, deleted: false } },
      logins: { 'b.com|x': login('b.com|x', 'b.com', 'x', 'remote-pw', 7) } };
    const res = await fetch(server + '/v1/blob', { method: 'PUT', body: await d.cx.encrypt(old.key, doc), headers: { Authorization: 'Bearer ' + old.token, 'If-None-Match': '*' } });
    assert.equal(res.status, 200);
  }
  return old;
}

test('unlock migrates local vault and server copy to Argon2id, merges both sides, retires the old blob', async () => {
  const { srv, dir, base } = await startServer();
  try {
    const A = device();
    const old = await legacyInstall(A, base, true);
    assert.equal((await A.core.status()).upgradePending, true);

    await A.core.unlock({ username: USER, secret: SECRET });
    const st = await A.core.status();
    assert.equal(st.kdf, 'argon2id-v2'); assert.equal(st.upgradePending, false); assert.equal(st.lastError, '');
    assert.equal((await A.m.browser.storage.local.get('vf_setup')).vf_setup.kdf, 'argon2id-v2');
    assert.equal(A.core.getSecret('a.com|me'), 'local-pw'); assert.equal(A.core.getSecret('b.com|x'), 'remote-pw');
    assert.deepEqual(A.urls(), ['https://r.example/']);

    // old (weaker) copy is gone, new copy exists and is readable only with the Argon2id key
    assert.equal((await fetch(base + '/v1/blob', { headers: { Authorization: 'Bearer ' + old.token } })).status, 404);
    const neu = await A.cx.deriveKeys(USER, SECRET, 'argon2id-v2');
    const got = await fetch(base + '/v1/blob', { headers: { Authorization: 'Bearer ' + neu.token } });
    assert.equal(got.status, 200);
    const doc = await A.cx.decrypt(neu.key, await got.text());
    assert.equal(doc.kdf, 'argon2id-v2'); assert.ok(doc.logins['a.com|me'] && doc.logins['b.com|x']);
    assert.ok(!/local-pw|remote-pw|a\.com/.test(fs.readdirSync(dir).map((f) => fs.readFileSync(path.join(dir, f), 'utf8')).join('')));

    // survives a lock/unlock cycle and a restart-style fresh unlock
    A.core.lock();
    await assert.rejects(() => A.core.unlock({ username: USER, secret: 'not-the-secret-xx' }), /Wrong/);
    await A.core.unlock({ username: USER, secret: SECRET });
    assert.equal(A.core.getSecret('b.com|x'), 'remote-pw');

    // a second device that never saw PBKDF2 joins with the same credentials
    const B = device();
    await B.core.setup({ username: USER, secret: SECRET, server: base });
    assert.equal(B.core.getSecret('a.com|me'), 'local-pw'); assert.deepEqual(B.urls(), ['https://r.example/']);
  } finally { stop(srv); }
});

test('second legacy device upgrades later and merges into the already-migrated server copy', async () => {
  const { srv, base } = await startServer();
  try {
    const A = device(), B = device();
    await legacyInstall(A, base, true);
    await A.core.unlock({ username: USER, secret: SECRET });             // A migrates first; old blob deleted
    await legacyInstall(B, base, false);                                 // B still has only its local PBKDF2 vault
    await B.core.unlock({ username: USER, secret: SECRET });
    assert.equal((await B.core.status()).kdf, 'argon2id-v2');
    assert.equal(B.core.getSecret('b.com|x'), 'remote-pw');               // came from A's migrated copy
    await A.core.syncNow(); assert.equal(A.core.getSecret('a.com|me'), 'local-pw');
  } finally { stop(srv); }
});

test('upgrade is offline-safe: unlock still works, stays on PBKDF2, retries on next unlock', async () => {
  const { srv, base } = await startServer();
  try {
    const A = device();
    await legacyInstall(A, 'http://127.0.0.1:1', false);                 // unreachable server
    await A.core.unlock({ username: USER, secret: SECRET });
    let st = await A.core.status();
    assert.equal(st.unlocked, true); assert.equal(st.upgradePending, true); assert.match(st.lastError, /upgrade.*pending/i);
    assert.equal(A.core.getSecret('a.com|me'), 'local-pw');
    assert.equal((await A.m.browser.storage.local.get('vf_setup')).vf_setup.kdf, undefined);   // nothing half-migrated

    await A.m.browser.storage.local.set({ vf_server: base });            // back online
    A.core.lock(); await A.core.unlock({ username: USER, secret: SECRET });
    st = await A.core.status(); assert.equal(st.upgradePending, false); assert.equal(st.kdf, 'argon2id-v2');
    assert.equal(A.core.getSecret('a.com|me'), 'local-pw');
  } finally { stop(srv); }
});

test('upgrade without any sync server just converts the local vault', async () => {
  const A = device();
  await legacyInstall(A, '', false);
  await A.core.unlock({ username: USER, secret: SECRET });
  assert.equal((await A.core.status()).kdf, 'argon2id-v2');
  A.core.lock(); await A.core.unlock({ username: USER, secret: SECRET });
  assert.equal(A.core.getSecret('a.com|me'), 'local-pw');
});

test('QR pairing: device A shows a code, device B joins from it and receives everything', async () => {
  const { srv, base } = await startServer();
  try {
    const A = device(), B = device();
    await A.core.setup({ username: USER, secret: SECRET, server: base });
    await A.core.saveLogin({ host: 'github.com', username: 'iqbal', password: 'pw-qr' });
    await A.core.syncNow();

    await assert.rejects(() => A.core.pairingPayload('wrong-key-wrong-key'), /not the secret key/);
    const code = await A.core.pairingPayload(SECRET);
    const p = B.common.decodePairing(code);
    assert.deepEqual([p.username, p.secret, p.server], [USER, SECRET, base]);

    await B.core.setup({ username: p.username, secret: p.secret, server: p.server });
    assert.equal(B.core.getSecret('github.com|iqbal'), 'pw-qr');
    await assert.rejects(() => B.core.setup({ username: p.username, secret: p.secret, server: p.server }), /already set up/);
    A.core.lock();
    await assert.rejects(() => A.core.pairingPayload(SECRET), /locked/);   // locked vault reveals nothing
  } finally { stop(srv); }
});
