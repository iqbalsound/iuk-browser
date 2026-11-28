/* Login detection, fill and capture (application world, top frame only). Talks to Python over QWebChannel. */
(function () {
  if (window.__iukAutofillInstalled) return;
  window.__iukAutofillInstalled = true;
  var bridge = null;
  if (window.qt && window.qt.webChannelTransport && window.QWebChannel) {
    new QWebChannel(window.qt.webChannelTransport, function (ch) { bridge = ch.objects.iukBridge; });
  }
  var TEXTY = ['text', 'email', 'tel', ''];
  function visible(el) { return el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden'; }
  function setVal(el, v) {
    var d = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), 'value');
    if (d && d.set) d.set.call(el, v); else el.value = v;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  function findFields(scope) {
    scope = scope || document;
    var pws = Array.prototype.filter.call(scope.querySelectorAll('input[type=password]'), visible);
    var pw = pws[0] || null;
    var root = (pw && pw.form) || scope;
    var cands = Array.prototype.filter.call(root.querySelectorAll('input'), function (i) {
      return TEXTY.indexOf((i.type || '').toLowerCase()) >= 0 && visible(i);
    });
    var user = null;
    if (pw) {
      var before = cands.filter(function (c) { return c.compareDocumentPosition(pw) & Node.DOCUMENT_POSITION_FOLLOWING; });
      user = before.length ? before[before.length - 1] : null;
    } else {
      user = cands.filter(function (c) { return /user|email|login/i.test((c.autocomplete || '') + c.name + c.id); })[0] || null;
    }
    return { pw: pw, user: user };
  }
  window.__iukFill = function (username, password) {
    var f = findFields();
    if (f.user && username) setVal(f.user, username);
    if (f.pw && password) setVal(f.pw, password);
    return !!(f.user || f.pw);
  };
  window.__iukHasLoginForm = function () { return !!findFields().pw; };

  var last = '';
  function capture(scope) {
    var pws = Array.prototype.filter.call((scope || document).querySelectorAll('input[type=password]'), function (p) { return p.value; });
    if (!pws.length || !bridge) return;
    var f = findFields(pws[0].form || document);
    var username = f.user ? f.user.value : '';
    var sig = username + '\u0000' + pws[0].value;
    if (sig === last) return;
    last = sig;
    bridge.captured(username, pws[0].value);
  }
  document.addEventListener('submit', function (e) { capture(e.target); }, true);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && e.target && e.target.type === 'password') capture(e.target.form || document);
  }, true);
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('button, input[type=submit]');
    if (b) capture(b.form || document);
  }, true);
})();
