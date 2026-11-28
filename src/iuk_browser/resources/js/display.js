/* Color invert + page filters (application world). Mirrors iuk_browser/core/display.py. */
(function () {
  var ID = 'iuk-display-style';
  var DEF = { mode: 'off', sites: [], brightness: 100, contrast: 100, sepia: 0, keepMedia: true };
  function css(s, host) {
    s = Object.assign({}, DEF, s || {});
    var on = s.mode === 'all' || (s.mode === 'sites' && s.sites.map(function (x) { return String(x).toLowerCase(); }).indexOf(host.toLowerCase()) >= 0);
    var f = [];
    if (on) f.push('invert(1) hue-rotate(180deg)');
    if (s.brightness !== 100) f.push('brightness(' + s.brightness + '%)');
    if (s.contrast !== 100) f.push('contrast(' + s.contrast + '%)');
    if (s.sepia > 0) f.push('sepia(' + s.sepia + '%)');
    if (!f.length) return '';
    var out = 'html{filter:' + f.join(' ') + ' !important;' + (on ? 'background:#fff;' : '') + '}';
    if (on && s.keepMedia) out += 'img,picture,video,canvas,[style*="background-image"]{filter:invert(1) hue-rotate(180deg) !important;}';
    return out;
  }
  function apply(s) {
    window.__iukDisplay = s;
    var c = css(s, location.hostname);
    var el = document.getElementById(ID);
    if (!c) { if (el) el.remove(); return; }
    var root = document.head || document.documentElement;
    if (!root) {   // injected at document creation: wait for <html> to appear, still before the first paint
      var mo = new MutationObserver(function () {
        if (document.documentElement) { mo.disconnect(); apply(window.__iukDisplay); }
      });
      mo.observe(document, { childList: true });
      return;
    }
    if (!el) { el = document.createElement('style'); el.id = ID; root.appendChild(el); }
    el.textContent = c;
  }
  window.__iukApplyDisplay = apply;
  apply(/*SETTINGS*/{});
})();
