/* Login detection, fill and "save password?" prompt. Top frame only; fills only on explicit user action. */
(function () {
  const visible = (el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const TEXTY = ['text', 'email', 'tel', ''];

  function setVal(el, v) {
    const d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value');
    (d && d.set ? d.set : (x) => { el.value = x; }).call(el, v);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function findFields(scope) {
    scope = scope || document;
    const pw = [...scope.querySelectorAll('input[type=password]')].filter(visible)[0] || null;
    const root = (pw && pw.form) || scope;
    const cands = [...root.querySelectorAll('input')].filter((i) => TEXTY.includes((i.type || '').toLowerCase()) && visible(i));
    let user = null;
    if (pw) user = cands.filter((c) => c.compareDocumentPosition(pw) & Node.DOCUMENT_POSITION_FOLLOWING).pop() || null;
    else user = cands.find((c) => /user|email|login/i.test(c.autocomplete + c.name + c.id)) || null;
    return { pw, user };
  }

  browser.runtime.onMessage.addListener((m) => {
    if (m && m.type === 'fill') {
      const { pw, user } = findFields();
      if (user && m.username) setVal(user, m.username);
      if (pw && m.password) setVal(pw, m.password);
      return Promise.resolve({ filled: !!(user || pw) });
    }
  });

  // ---- capture submitted credentials ----
  let last = '';
  function capture(scope) {
    const pws = [...(scope || document).querySelectorAll('input[type=password]')].filter((p) => p.value);
    if (!pws.length) return;
    const { user } = findFields(pws[0].form || document);
    const username = user ? user.value : '';
    const sig = username + '\u0000' + pws[0].value;
    if (sig === last) return; last = sig;
    browser.runtime.sendMessage({ type: 'captured', username, password: pws[0].value }).then(() => {
      setTimeout(showPrompt, 1500); // if the page navigates, the next page asks instead
    }).catch(() => {});
  }
  document.addEventListener('submit', (e) => capture(e.target), true);
  document.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.type === 'password') capture(e.target.form || document); }, true);
  document.addEventListener('click', (e) => {
    const b = e.target.closest && e.target.closest('button, input[type=submit]');
    if (b) capture(b.form || document);
  }, true);

  // ---- save prompt (closed shadow DOM so the page can't read or click it) ----
  let shown = false;
  async function showPrompt() {
    if (shown) return;
    const p = await browser.runtime.sendMessage({ type: 'getPending' }).catch(() => null);
    if (!p || !p.host) return;
    shown = true;
    const host = document.createElement('div');
    host.style.cssText = 'all:initial;position:fixed;top:12px;right:12px;z-index:2147483647;';
    if (document.getElementById('vf-display-style')) host.style.filter = 'invert(1) hue-rotate(180deg)';
    const root = host.attachShadow({ mode: 'closed' });
    const style = document.createElement('style');
    style.textContent = '.b{font:13px system-ui,sans-serif;background:#1c1b22;color:#fbfbfe;border:1px solid #5b5b66;border-radius:8px;padding:12px;width:290px;box-shadow:0 4px 18px #0007}' +
      'p{margin:0 0 10px}button{font:inherit;margin-right:6px;padding:5px 12px;border-radius:5px;border:0;cursor:pointer}' +
      '.y{background:#0060df;color:#fff}.n{background:#42414d;color:#fff}';
    const box = document.createElement('div'); box.className = 'b';
    const msg = document.createElement('p');
    msg.textContent = (p.kind === 'update' ? 'Update the saved password for ' : 'Save password for ') + (p.username || '(no user name)') + ' on ' + p.host + '?';
    const yes = document.createElement('button'); yes.className = 'y'; yes.textContent = p.kind === 'update' ? 'Update' : 'Save';
    const no = document.createElement('button'); no.className = 'n'; no.textContent = 'Not now';
    const close = () => { host.remove(); shown = false; };
    yes.addEventListener('click', () => { browser.runtime.sendMessage({ type: 'savePending' }).finally(close); });
    no.addEventListener('click', () => { browser.runtime.sendMessage({ type: 'dismissPending' }).finally(close); });
    box.append(msg, yes, no); root.append(style, box);
    document.documentElement.appendChild(host);
  }
  showPrompt(); // after a navigation caused by the login submit
})();
