/* Color invert + page filters. Runs at document_start so there is no white flash. */
(function () {
  const ID = 'vf-display-style';
  const host = location.hostname;
  function apply(settings) {
    const css = VFCommon.displayCSS(settings, host);
    let el = document.getElementById(ID);
    if (!css) { if (el) el.remove(); return; }
    if (!el) {
      el = document.createElement('style'); el.id = ID;
      (document.head || document.documentElement).appendChild(el);
    }
    el.textContent = css;
  }
  browser.storage.local.get('vf_display').then((r) => apply(r.vf_display));
  browser.storage.onChanged.addListener((ch, area) => { if (area === 'local' && ch.vf_display) apply(ch.vf_display.newValue); });
})();
