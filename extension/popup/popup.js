/* Toolbar popup: setup / unlock / logins / add / display / generator. DOM built with textContent only. */
const app = document.getElementById('app');
const h = (tag, props, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, '');
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return e;
};
const send = (type, data) => browser.runtime.sendMessage(Object.assign({ type }, data)).then((r) => {
  if (r && r.error) throw new Error(r.error);
  return r;
});
const copy = (text) => navigator.clipboard.writeText(text);
const mount = (...nodes) => { app.replaceChildren(...nodes); };
const msg = (cls, text) => h('div', { class: cls }, text);

let tab = 'site', tabInfo = { host: '', id: null, web: false }, flash = null;

async function init() {
  const [t] = await browser.tabs.query({ active: true, currentWindow: true });
  if (t && /^https?:/.test(t.url || '')) tabInfo = { host: new URL(t.url).hostname, id: t.id, web: true };
  render();
}

async function render() {
  const s = await send('status');
  if (!s.setup) return viewSetup();
  if (!s.unlocked) return viewUnlock(s);
  return viewMain(s);
}

// ---------- setup / unlock ----------
function viewSetup() {
  const user = h('input', { type: 'email', placeholder: 'User name or e-mail (same on every device)', autocomplete: 'off' });
  const secret = h('input', { type: 'password', placeholder: 'Secret connectivity key (min 12 chars)', autocomplete: 'off' });
  const server = h('input', { type: 'url', placeholder: 'Sync server URL (optional), e.g. https://sync.example.com' });
  const err = h('div');
  const gen = h('button', { onclick: () => { secret.type = 'text'; secret.value = VFCommon.genPassword(32); } }, 'Generate key');
  const go = h('button', { class: 'primary', onclick: async () => {
    go.disabled = true; err.replaceChildren(h('div', { class: 'muted' }, 'Deriving key (takes a moment)…'));
    try { await send('setup', { username: user.value, secret: secret.value, server: server.value }); render(); }
    catch (e) { go.disabled = false; err.replaceChildren(msg('err', e.message)); }
  } }, 'Create vault');
  mount(h('h1', {}, 'Set up IUK Browser'),
    h('p', { class: 'muted' }, 'Use the same user name and secret key on your other device to sync. The key never leaves this device and cannot be recovered. Write it down.'),
    h('div', { class: 'col' }, user, h('div', { class: 'row' }, secret, gen), server, err, go,
      h('button', { onclick: () => { browser.tabs.create({ url: browser.runtime.getURL('pair/pair.html#scan') }); window.close(); } }, 'Scan pairing QR from another device')));
}

function viewUnlock(s) {
  const user = h('input', { type: 'email', value: s.username });
  const secret = h('input', { type: 'password', placeholder: 'Secret connectivity key', autocomplete: 'off' });
  const err = h('div');
  const go = async () => {
    err.replaceChildren(h('div', { class: 'muted' }, s.upgradePending ? 'Unlocking and upgrading key protection to Argon2id (takes a few seconds)…' : 'Unlocking…'));
    try { await send('unlock', { username: user.value, secret: secret.value }); render(); }
    catch (e) { err.replaceChildren(msg('err', e.message)); }
  };
  secret.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  mount(h('h1', {}, 'Unlock IUK Browser'), h('div', { class: 'col' }, user, secret, err, h('button', { class: 'primary', onclick: go }, 'Unlock')));
  secret.focus();
}

// ---------- main ----------
async function viewMain(s) {
  const when = s.lastSync ? new Date(s.lastSync).toLocaleString() : 'never';
  const syncLine = s.lastError ? msg('err', 'Sync error: ' + s.lastError) : h('div', { class: 'muted' }, s.server ? 'Last sync: ' + when : 'Sync server not set (local only)');
  const head = h('div', { class: 'row' }, h('h1', {}, 'IUK Browser'),
    h('button', { title: 'Sync now', onclick: async (e) => { e.target.disabled = true; try { await send('sync'); flash = 'Synced'; } catch (er) { flash = null; } render(); } }, '⟳'),
    h('button', { title: 'Pair another device (QR)', onclick: () => { browser.tabs.create({ url: browser.runtime.getURL('pair/pair.html#show') }); window.close(); } }, 'QR'),
    h('button', { title: 'Lock', onclick: async () => { await send('lock'); render(); } }, 'Lock'),
    h('button', { title: 'Settings', onclick: () => { browser.runtime.openOptionsPage(); window.close(); } }, '⚙'));
  const names = { site: 'This site', all: 'All', add: 'Add', display: 'Display', gen: 'Generator' };
  const tabs = h('div', { class: 'tabs' }, Object.entries(names).map(([k, v]) =>
    h('button', { class: tab === k ? 'on' : '', onclick: () => { tab = k; flash = null; render(); } }, v)));
  const body = h('div');
  const upgrade = s.upgradePending ? msg('err', 'Key protection upgrade pending. Lock and unlock again while online to finish it.') : null;
  mount(head, syncLine, upgrade, flash ? msg('ok', flash) : null, tabs, body);
  const views = { site: tabSite, all: tabAll, add: tabAdd, display: tabDisplay, gen: tabGen };
  await views[tab](body);
}

function loginCard(l, extra) {
  return h('div', { class: 'item' },
    h('div', { class: 't' }, l.host), h('div', { class: 's' }, l.username || '(no user name)'),
    h('div', { class: 'row' },
      extra,
      h('button', { onclick: () => copy(l.username) }, 'Copy user'),
      h('button', { onclick: async () => { await copy(await send('secret', { id: l.id })); flash = 'Password copied'; render(); } }, 'Copy pass'),
      h('button', { class: 'danger', onclick: async () => { if (confirm('Delete login for ' + l.host + '?')) { await send('remove', { id: l.id }); render(); } } }, 'Delete')));
}

async function tabSite(body) {
  if (!tabInfo.web) return body.replaceChildren(h('p', { class: 'muted' }, 'Open a website to see matching logins.'));
  const list = await send('list', { host: tabInfo.host });
  if (!list.length) return body.replaceChildren(h('p', { class: 'muted' }, 'No saved logins for ' + tabInfo.host + '. Log in once and IUK Browser will offer to save it.'));
  body.replaceChildren(...list.map((l) => loginCard(l, h('button', { class: 'primary', onclick: async () => {
    try { await send('fill', { tabId: tabInfo.id, id: l.id }); window.close(); } catch (e) { flash = null; body.prepend(msg('err', e.message)); }
  } }, 'Fill'))));
}

async function tabAll(body) {
  const all = await send('list', {});
  const q = h('input', { type: 'text', placeholder: 'Search ' + all.length + ' logins…' });
  const out = h('div');
  const draw = () => {
    const t = q.value.toLowerCase();
    out.replaceChildren(...all.filter((l) => !t || (l.host + ' ' + l.username).toLowerCase().includes(t)).slice(0, 50).map((l) => loginCard(l)));
  };
  q.addEventListener('input', draw); draw();
  body.replaceChildren(q, out);
}

function tabAdd(body) {
  const host = h('input', { type: 'text', placeholder: 'Site, e.g. example.com', value: tabInfo.host });
  const user = h('input', { type: 'text', placeholder: 'User name' });
  const pass = h('input', { type: 'password', placeholder: 'Password' });
  const notes = h('textarea', { rows: 2, placeholder: 'Notes (optional)' });
  const err = h('div');
  body.replaceChildren(h('div', { class: 'col' }, host, user,
    h('div', { class: 'row' }, pass, h('button', { onclick: () => { pass.type = 'text'; pass.value = VFCommon.genPassword(20); } }, 'Generate')),
    notes, err,
    h('button', { class: 'primary', onclick: async () => {
      try { await send('save', { login: { host: host.value, username: user.value, password: pass.value, notes: notes.value } }); flash = 'Saved'; tab = 'all'; render(); }
      catch (e) { err.replaceChildren(msg('err', e.message)); }
    } }, 'Save login')));
}

async function tabDisplay(body) {
  const r = await browser.storage.local.get('vf_display');
  const d = VFCommon.normDisplay(r.vf_display);
  const save = () => browser.storage.local.set({ vf_display: d });
  const slider = (label, key, min, max) => {
    const val = h('span', {}, d[key] + '%');
    const inp = h('input', { type: 'range', min, max, value: d[key] });
    inp.addEventListener('input', () => { d[key] = +inp.value; val.textContent = d[key] + '%'; save(); });
    return h('div', {}, h('div', { class: 'row' }, label + ': ', val), inp);
  };
  const siteBox = h('input', { type: 'checkbox', disabled: !tabInfo.web, checked: d.mode === 'sites' && d.sites.includes(tabInfo.host) });
  siteBox.addEventListener('change', () => {
    if (siteBox.checked) { if (d.mode === 'off') d.mode = 'sites'; if (!d.sites.includes(tabInfo.host)) d.sites.push(tabInfo.host); }
    else { d.sites = d.sites.filter((x) => x !== tabInfo.host); if (d.mode === 'sites' && !d.sites.length) d.mode = 'off'; }
    save();
  });
  const allBox = h('input', { type: 'checkbox', checked: d.mode === 'all' });
  allBox.addEventListener('change', () => { d.mode = allBox.checked ? 'all' : (d.sites.length ? 'sites' : 'off'); save(); });
  const mediaBox = h('input', { type: 'checkbox', checked: d.keepMedia });
  mediaBox.addEventListener('change', () => { d.keepMedia = mediaBox.checked; save(); });
  body.replaceChildren(
    h('label', { class: 'chk' }, siteBox, 'Invert colors on ' + (tabInfo.host || 'this site')),
    h('label', { class: 'chk' }, allBox, 'Invert colors on all sites (Alt+Shift+I)'),
    h('label', { class: 'chk' }, mediaBox, 'Keep images and video natural'),
    slider('Brightness', 'brightness', 50, 150), slider('Contrast', 'contrast', 50, 150), slider('Sepia', 'sepia', 0, 100));
}

function tabGen(body) {
  const out = h('code', { class: 'pw' }, VFCommon.genPassword(20));
  const len = h('input', { type: 'range', min: 8, max: 64, value: 20 });
  const lab = h('span', {}, '20');
  const regen = () => { lab.textContent = len.value; out.textContent = VFCommon.genPassword(+len.value); };
  len.addEventListener('input', regen);
  body.replaceChildren(out, h('div', { class: 'row' }, 'Length: ', lab), len,
    h('div', { class: 'row' }, h('button', { onclick: regen }, 'Regenerate'),
      h('button', { class: 'primary', onclick: () => { copy(out.textContent); flash = null; } }, 'Copy')));
}

init();
