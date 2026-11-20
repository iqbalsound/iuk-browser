/* Background entry point: message router, scheduled sync, shortcuts, browser theme. */
const EXT_BASE = browser.runtime.getURL('');
const CONTENT_TYPES = new Set(['captured', 'getPending', 'savePending', 'dismissPending']);

async function activeTab() {
  const [t] = await browser.tabs.query({ active: true, currentWindow: true });
  return t;
}

async function fillTab(tabId, loginId) {
  const tab = await browser.tabs.get(tabId);
  const host = new URL(tab.url).hostname;
  const login = VFCore.listLogins(host).find((l) => l.id === loginId);
  if (!login) throw new Error('This login does not match the current site');
  await browser.tabs.sendMessage(tabId, { type: 'fill', username: login.username, password: VFCore.getSecret(loginId) }, { frameId: 0 });
}

const handlers = {
  status: () => VFCore.status(),
  setup: async (m) => { await VFCore.setup(m); await refreshBadge(); },
  unlock: async (m) => { await VFCore.unlock(m); await refreshBadge(); VFCore.syncNow().catch(() => {}); },
  lock: async () => { VFCore.lock(); await refreshBadge(); },
  wipe: async () => { await VFCore.wipe(); await refreshBadge(); },
  setServer: (m) => VFCore.setServer(m.server),
  sync: () => VFCore.syncNow(),
  list: (m) => VFCore.listLogins(m.host),
  secret: (m) => VFCore.getSecret(m.id),
  save: (m) => VFCore.saveLogin(m.login).then((id) => { scheduleSync(); return id; }),
  remove: (m) => VFCore.removeLogin(m.id).then(scheduleSync),
  import: (m) => VFCore.importLogins(m.items).then((n) => { scheduleSync(); return n; }),
  export: () => VFCore.exportLogins(),
  fill: (m) => fillTab(m.tabId, m.id),
  // from content scripts (tab id comes from the sender, never from the page)
  captured: (m, s) => VFCore.capture(s.tab.id, new URL(s.tab.url).hostname, m.username, m.password),
  getPending: (m, s) => VFCore.takePending(s.tab.id, new URL(s.tab.url).hostname),
  savePending: (m, s) => VFCore.confirmPending(s.tab.id).then(scheduleSync),
  dismissPending: (m, s) => VFCore.dismissPending(s.tab.id),
};

browser.runtime.onMessage.addListener((msg, sender) => {
  const fn = handlers[msg && msg.type];
  if (!fn) return;
  const fromExtensionPage = (sender.url || '').startsWith(EXT_BASE);
  const fromContent = !!sender.tab && !fromExtensionPage;
  // Web-page-facing content scripts may only use the capture/save-prompt messages.
  if (fromContent ? !CONTENT_TYPES.has(msg.type) : !fromExtensionPage) return Promise.resolve({ error: 'Not allowed' });
  return Promise.resolve().then(() => fn(msg, sender)).then(
    (r) => (r === undefined ? {} : r),
    (e) => ({ error: String((e && e.message) || e) }),
  );
});

// ---------- sync scheduling ----------
let syncTimer = null;
function scheduleSync() {
  if (!VFCore.isUnlocked()) return;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => VFCore.syncNow().catch(() => {}), 5000);
}
browser.alarms.create('vf-sync', { periodInMinutes: 5 });
browser.alarms.onAlarm.addListener((a) => { if (a.name === 'vf-sync' && VFCore.isUnlocked()) VFCore.syncNow().catch(() => {}); });
for (const ev of ['onCreated', 'onRemoved', 'onChanged', 'onMoved']) {
  browser.bookmarks[ev].addListener(() => { if (!VFBookmarks.isApplying()) scheduleSync(); });
}

// ---------- badge ----------
async function refreshBadge() {
  const s = await VFCore.status();
  const locked = s.setup && !s.unlocked;
  await browser.browserAction.setBadgeText({ text: locked ? '!' : '' });
  await browser.browserAction.setBadgeBackgroundColor({ color: '#d70022' });
}

// ---------- theme ----------
async function applyTheme() {
  const t = await VFCore.get('vf_theme', { id: 'system' });
  if (!t || t.id === 'system') return browser.theme.reset();
  const base = t.id === 'custom' ? t : VFCommon.THEMES.find((x) => x.id === t.id);
  if (!base) return browser.theme.reset();
  return browser.theme.update(VFCommon.makeTheme(base.bg, base.fg, base.accent));
}
browser.storage.onChanged.addListener((ch, area) => { if (area === 'local' && ch.vf_theme) applyTheme(); });

// ---------- shortcuts ----------
browser.commands.onCommand.addListener(async (cmd) => {
  if (cmd === 'toggle-invert') {
    const d = VFCommon.normDisplay((await VFCore.get('vf_display', null)));
    d.mode = d.mode === 'all' ? 'off' : 'all';
    await VFCore.set({ vf_display: d });
  } else if (cmd === 'fill-login' && VFCore.isUnlocked()) {
    const tab = await activeTab();
    if (!tab || !/^https?:/.test(tab.url)) return;
    const [first] = VFCore.listLogins(new URL(tab.url).hostname);
    if (first) fillTab(tab.id, first.id).catch(() => {});
  }
});

browser.tabs.onRemoved.addListener((id) => VFCore.dismissPending(id));
browser.runtime.onStartup.addListener(() => { applyTheme(); refreshBadge(); });
browser.runtime.onInstalled.addListener(() => { applyTheme(); refreshBadge(); });
applyTheme(); refreshBadge();
