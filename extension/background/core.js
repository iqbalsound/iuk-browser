/* Vault + sync engine. Secrets (derived key, token, decrypted logins) live only in memory while unlocked. */
var VFCore = (function () {
  const C = VFCrypto, M = VFMerge;
  let session = null;      // { key, token, username, kdf }
  let logins = {};         // id -> login item (includes tombstones)
  let bmPrev = {};         // last known versioned bookmark state
  let syncing = null;
  const pending = new Map(); // tabId -> captured credentials awaiting "Save?" confirmation

  const get = async (k, d) => { const r = await browser.storage.local.get(k); return r[k] === undefined ? d : r[k]; };
  const set = (o) => browser.storage.local.set(o);
  const need = () => { if (!session) throw new Error('Vault is locked'); };

  function normServer(url) {
    url = String(url || '').trim().replace(/\/+$/, '');
    if (!url) return '';
    const u = new URL(url);
    if (u.protocol !== 'https:' && u.protocol !== 'http:') throw new Error('Server URL must be http(s)');
    return u.toString().replace(/\/+$/, '');
  }

  // ---------- transport ----------
  async function remoteFetch(server, token) {
    const res = await fetch(server + '/v1/blob', { headers: { Authorization: 'Bearer ' + token }, cache: 'no-store' });
    if (res.status === 404) return null;
    if (res.status === 401) throw new Error('Server rejected the sync token');
    if (!res.ok) throw new Error('Server error ' + res.status);
    return { etag: res.headers.get('ETag'), body: await res.text() };
  }
  async function remotePut(server, token, body, etag) {
    const res = await fetch(server + '/v1/blob', {
      method: 'PUT', body, cache: 'no-store',
      headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'text/plain', ...(etag ? { 'If-Match': etag } : { 'If-None-Match': '*' }) },
    });
    if (res.status === 412) return false;
    if (!res.ok) throw new Error('Upload failed: ' + res.status);
    return true;
  }
  async function remoteDelete(server, token) {
    try { await fetch(server + '/v1/blob', { method: 'DELETE', headers: { Authorization: 'Bearer ' + token }, cache: 'no-store' }); } catch (e) { /* best effort */ }
  }
  async function decryptDoc(key, body) {
    let doc;
    try { doc = await C.decrypt(key, body); } catch (e) { throw new Error('Synced data was encrypted with a different key'); }
    if (!doc || doc.v !== 1) throw new Error('Unsupported sync data version');
    return doc;
  }

  // ---------- session ----------
  async function status() {
    const s = await get('vf_setup', null);
    const kdf = session ? session.kdf : (s ? (s.kdf || C.KDF_LEGACY) : C.KDF_LATEST);
    return {
      setup: !!s, unlocked: !!session, username: s ? s.username : '', kdf, upgradePending: !!s && kdf === C.KDF_LEGACY,
      server: await get('vf_server', ''), lastSync: await get('vf_lastSync', 0), lastError: await get('vf_lastError', ''),
    };
  }

  async function persistLogins() { await set({ vf_logins_enc: await C.encrypt(session.key, logins) }); }

  async function setup({ username, secret, server }) {
    username = String(username || '').trim();
    if (!username) throw new Error('Enter a user name');
    if (!secret || secret.length < 12) throw new Error('Secret key must be at least 12 characters');
    if (await get('vf_setup', null)) throw new Error('This device is already set up. Use "Forget this device" in settings first.');
    server = normServer(server);
    const { key, token, kdf } = await C.deriveKeys(username, secret, C.KDF_LATEST);
    if (server) { // joining existing data? make sure the key actually matches before saving anything
      const r = await remoteFetch(server, token);
      if (r) await decryptDoc(key, r.body);
    }
    await set({
      vf_setup: { username, verifier: await C.encrypt(key, { ok: 'iuk-browser' }), kdf },
      vf_server: server, vf_bm_prev: {}, vf_logins_enc: await C.encrypt(key, {}), vf_lastError: '',
    });
    session = { key, token, username, kdf }; logins = {}; bmPrev = {};
    if (server) await syncNow();
  }

  async function unlock({ username, secret }) {
    const s = await get('vf_setup', null);
    if (!s) throw new Error('Not set up yet');
    if (String(username).trim().toLowerCase() !== s.username.toLowerCase()) throw new Error('Wrong user name or secret key');
    const kdf = s.kdf || C.KDF_LEGACY;
    const { key, token } = await C.deriveKeys(s.username, secret, kdf);
    try { await C.decrypt(key, s.verifier); } catch (e) { throw new Error('Wrong user name or secret key'); }
    session = { key, token, username: s.username, kdf };
    const enc = await get('vf_logins_enc', null);
    logins = enc ? await C.decrypt(key, enc) : {};
    bmPrev = await get('vf_bm_prev', {});
    if (kdf !== C.KDF_LATEST) {
      // Move this vault (and its server copy) from PBKDF2 to Argon2id. Failures are not fatal: the vault stays
      // usable with the old derivation and the upgrade is retried at the next unlock.
      try { await upgrade(s.username, secret); await set({ vf_lastError: '' }); }
      catch (e) { await set({ vf_lastError: 'Key upgrade to Argon2id pending: ' + String(e.message || e) }); }
    }
  }

  // PBKDF2 -> Argon2id. Everything is computed first; local state is switched in ONE storage write after the
  // new server copy is safely uploaded, so a crash or network error never leaves the vault half-migrated.
  async function upgrade(username, secret) {
    const next = await C.deriveKeys(username, secret, C.KDF_LATEST);
    const server = await get('vf_server', '');
    const now = Date.now();
    const local = { v: 1, bookmarks: M.reconcileLocal(bmPrev, await VFBookmarks.snapshotLocal(), now), logins };
    let doc = local, applyKeys = [], oldToken = null;
    if (server) {
      for (let attempt = 0; ; attempt++) {
        if (attempt >= 4) throw new Error('sync conflict during upgrade');
        const oldRemote = await remoteFetch(server, session.token);
        const newRemote = await remoteFetch(server, next.token);
        doc = local;
        if (oldRemote) doc = M.mergeDocs(doc, await decryptDoc(session.key, oldRemote.body), now).doc;
        if (newRemote) doc = M.mergeDocs(doc, await decryptDoc(next.key, newRemote.body), now).doc;
        applyKeys = M.mergeMaps(local.bookmarks, doc.bookmarks).changedLocal.filter((k) => doc.bookmarks[k]);
        const body = await C.encrypt(next.key, Object.assign({}, doc, { kdf: next.kdf }));
        if (await remotePut(server, next.token, body, newRemote && newRemote.etag)) { oldToken = oldRemote ? session.token : null; break; }
      }
    }
    if (applyKeys.length) await VFBookmarks.apply(doc.bookmarks, applyKeys);
    await set({
      vf_setup: { username, verifier: await C.encrypt(next.key, { ok: 'iuk-browser' }), kdf: next.kdf },
      vf_logins_enc: await C.encrypt(next.key, doc.logins), vf_bm_prev: doc.bookmarks,
    });
    const oldSessionToken = session.token;
    session = { key: next.key, token: next.token, username, kdf: next.kdf }; logins = doc.logins; bmPrev = doc.bookmarks;
    if (server && oldToken) await remoteDelete(server, oldSessionToken); // retire the weaker-KDF copy
  }

  // Pairing: another device can be set up by scanning a QR that carries user name + key + server. Requires the
  // key to be typed again (we never keep it), so an unlocked but unattended browser cannot reveal it.
  async function pairingPayload(secret) {
    need();
    const { token } = await C.deriveKeys(session.username, secret || '', session.kdf);
    if (token !== session.token) throw new Error('That is not the secret key of this vault');
    return VFCommon.encodePairing({ u: session.username, k: secret, s: await get('vf_server', '') });
  }

  function lock() { session = null; logins = {}; pending.clear(); }

  async function wipe() {
    lock();
    await browser.storage.local.remove(['vf_setup', 'vf_logins_enc', 'vf_bm_prev', 'vf_server', 'vf_lastSync', 'vf_lastError']);
  }

  async function setServer(server) {
    const s = normServer(server);
    await set({ vf_server: s });
    return s;
  }

  // ---------- logins ----------
  const live = () => Object.values(logins).filter((l) => !l.deleted);
  const strip = (l) => ({ id: l.id, host: l.host, username: l.username, notes: l.notes, updatedAt: l.updatedAt });

  function listLogins(host) {
    need();
    return live().filter((l) => !host || VFCommon.hostMatches(l.host, host)).map(strip)
      .sort((a, b) => a.host.localeCompare(b.host) || a.username.localeCompare(b.username));
  }
  function getSecret(id) { need(); const l = logins[id]; if (!l || l.deleted) throw new Error('Not found'); return l.password; }

  function putLogin({ host, username, password, notes }, now) {
    host = VFCommon.hostFrom(host); username = String(username || '');
    if (!host || !password) throw new Error('Site and password are required');
    const id = host + '|' + username.toLowerCase(); const prev = logins[id];
    logins[id] = { id, host, username, password, notes: notes || '', createdAt: (prev && prev.createdAt) || now, updatedAt: now, deleted: false };
    return id;
  }
  async function saveLogin(item) { need(); const id = putLogin(item, Date.now()); await persistLogins(); return id; }
  async function importLogins(items) {
    need(); const now = Date.now(); let n = 0;
    for (const it of items) { try { putLogin(it, now); n++; } catch (e) { /* skip bad rows */ } }
    await persistLogins(); return n;
  }
  async function removeLogin(id) {
    need(); if (!logins[id]) return;
    logins[id] = { id, deleted: true, updatedAt: Date.now() }; await persistLogins();
  }
  function exportLogins() { need(); return live().map((l) => ({ host: l.host, username: l.username, password: l.password, notes: l.notes })); }

  // Capture flow: content script reports a submitted form; we hold it until the next page asks.
  function capture(tabId, host, username, password) {
    if (!session || !password) return { status: 'locked' };
    const id = VFCommon.hostFrom(host) + '|' + String(username || '').toLowerCase();
    const ex = logins[id];
    if (ex && !ex.deleted && ex.password === password) return { status: 'known' };
    pending.set(tabId, { host, username, password, kind: ex && !ex.deleted ? 'update' : 'new', ts: Date.now() });
    return { status: 'pending' };
  }
  function takePending(tabId, host) {
    const p = pending.get(tabId);
    if (!p || Date.now() - p.ts > 120000 || !VFCommon.hostMatches(p.host, host)) return null;
    pending.delete(tabId);
    pending.set('open:' + tabId, p);
    return { host: p.host, username: p.username, kind: p.kind };
  }
  async function confirmPending(tabId) {
    const p = pending.get('open:' + tabId); if (!p) throw new Error('Nothing to save');
    pending.delete('open:' + tabId); return saveLogin(p);
  }
  const dismissPending = (tabId) => { pending.delete(tabId); pending.delete('open:' + tabId); };

  // ---------- sync ----------
  async function doSync() {
    const server = await get('vf_server', '');
    const now = Date.now();
    let bmCur = M.reconcileLocal(bmPrev, await VFBookmarks.snapshotLocal(), now);
    if (!server) { bmPrev = bmCur; await set({ vf_bm_prev: bmPrev }); return { offline: true }; }
    for (let attempt = 0; attempt < 4; attempt++) {
      const remote = await remoteFetch(server, session.token);
      const remoteDoc = remote ? await decryptDoc(session.key, remote.body) : null;
      const m = M.mergeDocs({ v: 1, bookmarks: bmCur, logins }, remoteDoc, now);
      if (m.changed.bookmarks.length) await VFBookmarks.apply(m.doc.bookmarks, m.changed.bookmarks);
      logins = m.doc.logins; bmCur = m.doc.bookmarks; bmPrev = bmCur;
      await persistLogins(); await set({ vf_bm_prev: bmPrev });
      if (!remote || m.pushNeeded) {
        const ok = await remotePut(server, session.token, await C.encrypt(session.key, Object.assign({}, m.doc, { kdf: session.kdf })), remote && remote.etag);
        if (!ok) continue; // someone else wrote first; re-fetch and merge again
      }
      return { pulled: m.changed.bookmarks.length + m.changed.logins.length };
    }
    throw new Error('Sync conflict, please try again');
  }

  function syncNow() {
    need();
    if (syncing) return syncing;
    syncing = (async () => {
      try { const r = await doSync(); await set({ vf_lastSync: Date.now(), vf_lastError: '' }); return r; }
      catch (e) { await set({ vf_lastError: String(e.message || e) }); throw e; }
      finally { syncing = null; }
    })();
    return syncing;
  }

  const isUnlocked = () => !!session;
  return { status, setup, unlock, lock, wipe, setServer, listLogins, getSecret, saveLogin, importLogins, removeLogin,
           exportLogins, pairingPayload, capture, takePending, confirmPending, dismissPending, syncNow, isUnlocked, get, set };
})();
