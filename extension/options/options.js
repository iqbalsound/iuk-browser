/* Settings page: sync server, themes, page display, import/export, forget device. */
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
const send = (type, data) => browser.runtime.sendMessage(Object.assign({ type }, data)).then((r) => { if (r && r.error) throw new Error(r.error); return r; });
const note = (el, cls, text) => { el.className = cls; el.textContent = text; };

async function build() {
  const s = await send('status');
  const store = await browser.storage.local.get(['vf_theme', 'vf_display']);
  const theme = store.vf_theme || { id: 'system' };
  const d = VFCommon.normDisplay(store.vf_display);

  // ---- Sync ----
  const server = h('input', { type: 'url', value: s.server, placeholder: 'https://sync.example.com' });
  const syncMsg = h('div');
  if (/^http:\/\//.test(s.server) && !/^http:\/\/(localhost|127\.)/.test(s.server)) note(syncMsg, 'muted', 'Warning: plain http. Data is still end-to-end encrypted, but use https if you can.');
  const secSync = h('section', {}, h('h2', {}, 'Sync'),
    h('p', { class: 'muted' }, 'Signed in as ' + (s.username || '(not set up)') + '. Bookmarks and passwords are encrypted on this device before upload; the server stores only ciphertext.'),
    server,
    h('div', { class: 'row' },
      h('button', { class: 'primary', onclick: async () => {
        try { await send('setServer', { server: server.value }); if (s.unlocked) await send('sync'); note(syncMsg, 'ok', 'Saved' + (s.unlocked ? ' and synced.' : '. Unlock the vault from the toolbar popup to sync.')); }
        catch (e) { note(syncMsg, 'err', e.message); }
      } }, 'Save and sync')), syncMsg);

  const secPair = h('section', {}, h('h2', {}, 'Pair another device'),
    h('p', { class: 'muted' }, 'Show a QR code on this device and scan it with the new one, so you never retype the secret key. Key protection: ' + (s.kdf === 'argon2id-v2' ? 'Argon2id' : 'PBKDF2 (will upgrade to Argon2id the next time you unlock)') + '.'),
    h('div', { class: 'row' },
      h('button', { class: 'primary', onclick: () => browser.tabs.create({ url: browser.runtime.getURL('pair/pair.html#show') }) }, 'Show pairing QR'),
      h('button', { onclick: () => browser.tabs.create({ url: browser.runtime.getURL('pair/pair.html#scan') }) }, 'Scan a QR on this device')));

  // ---- Theme ----
  const pick = async (t) => { await browser.storage.local.set({ vf_theme: t }); build(); };
  const card = (id, name, bg, fg, accent) => h('button', { class: 'sw' + (theme.id === id ? ' on' : ''), onclick: () => pick(id === 'system' ? { id } : { id }) },
    h('div', { class: 'bar', style: 'background:' + bg + ';color:' + fg + ';border-bottom:3px solid ' + accent }, name), name);
  const cust = { bg: theme.bg || '#1c1b22', fg: theme.fg || '#fbfbfe', accent: theme.accent || '#00ddff' };
  const color = (key, label) => h('label', { class: 'row' }, h('input', { type: 'color', value: cust[key], onchange: (e) => { cust[key] = e.target.value; } }), label);
  const secTheme = h('section', {}, h('h2', {}, 'Browser theme'),
    h('div', { class: 'themes' }, card('system', 'Default', '#e7e7ea', '#15141a', '#0060df'),
      VFCommon.THEMES.map((t) => card(t.id, t.name, t.bg, t.fg, t.accent))),
    h('h3', {}, 'Custom'),
    h('div', { class: 'row' }, color('bg', 'Background'), color('fg', 'Text'), color('accent', 'Accent'),
      h('button', { onclick: () => pick({ id: 'custom', ...cust }) }, 'Apply custom')));

  // ---- Display ----
  const saveD = () => browser.storage.local.set({ vf_display: d });
  const radio = (val, label) => h('label', { class: 'row' }, h('input', { type: 'radio', name: 'mode', checked: d.mode === val, onchange: () => { d.mode = val; saveD(); } }), label);
  const slider = (label, key, min, max) => {
    const v = h('span', {}, d[key] + '%');
    return h('div', { class: 'row' }, h('span', { style: 'width:90px' }, label),
      h('input', { type: 'range', min, max, value: d[key], oninput: (e) => { d[key] = +e.target.value; v.textContent = d[key] + '%'; saveD(); } }), v);
  };
  const sites = h('textarea', { rows: 3, placeholder: 'one host per line, e.g. news.ycombinator.com' }, d.sites.join('\n'));
  sites.addEventListener('change', () => { d.sites = sites.value.split(/\n+/).map((x) => VFCommon.hostFrom(x)).filter(Boolean); saveD(); });
  const secDisplay = h('section', {}, h('h2', {}, 'Color invert and page filters'),
    radio('off', 'Off'), radio('sites', 'Only on the sites listed below'), radio('all', 'On all sites (Alt+Shift+I toggles)'), sites,
    h('label', { class: 'row' }, h('input', { type: 'checkbox', checked: d.keepMedia, onchange: (e) => { d.keepMedia = e.target.checked; saveD(); } }), 'Keep images and video natural when inverted'),
    slider('Brightness', 'brightness', 50, 150), slider('Contrast', 'contrast', 50, 150), slider('Sepia', 'sepia', 0, 100));

  // ---- Passwords ----
  const pwMsg = h('div');
  const file = h('input', { type: 'file', accept: '.csv,text/csv', hidden: true });
  file.addEventListener('change', async () => {
    try {
      const items = VFCommon.loginsFromCSV(VFCommon.parseCSV(await file.files[0].text()));
      const n = await send('import', { items }); note(pwMsg, 'ok', 'Imported ' + n + ' logins. Delete the CSV file now; it contains plain-text passwords.');
    } catch (e) { note(pwMsg, 'err', e.message.includes('locked') ? 'Unlock the vault first (toolbar popup).' : e.message); }
    file.value = '';
  });
  const secPw = h('section', {}, h('h2', {}, 'Passwords'),
    h('p', { class: 'muted' }, 'Import from a Firefox, Chrome or Edge CSV export. Export is plain text; store it safely and delete it afterwards.'),
    h('div', { class: 'row' }, h('button', { onclick: () => file.click() }, 'Import CSV…'), file,
      h('button', { onclick: async () => {
        if (!confirm('The export contains all passwords in plain text. Continue?')) return;
        try {
          const rows = [['url', 'username', 'password', 'note']].concat((await send('export')).map((l) => ['https://' + l.host, l.username, l.password, l.notes]));
          const a = h('a', { href: URL.createObjectURL(new Blob([VFCommon.toCSV(rows)], { type: 'text/csv' })), download: 'iuk-browser-passwords.csv' });
          document.body.append(a); a.click(); a.remove();
        } catch (e) { note(pwMsg, 'err', 'Unlock the vault first (toolbar popup).'); }
      } }, 'Export CSV…')), pwMsg);

  // ---- Danger ----
  const secDanger = h('section', {}, h('h2', {}, 'Forget this device'),
    h('p', { class: 'muted' }, 'Removes the local vault and sync settings from this browser. Data already on the sync server is untouched.'),
    h('button', { class: 'danger', onclick: async () => { if (confirm('Remove the local vault from this device?')) { await send('wipe'); build(); } } }, 'Forget this device'));

  app.replaceChildren(h('h1', {}, 'IUK Browser settings'), secSync, secPair, secTheme, secDisplay, secPw, secDanger);
}
build();
