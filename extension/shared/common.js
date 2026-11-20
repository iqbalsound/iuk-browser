/* Shared helpers: display (color invert) CSS, themes, password generator, CSV. */
var VFCommon = (function () {
  const DISPLAY_DEFAULT = { mode: 'off', sites: [], brightness: 100, contrast: 100, sepia: 0, keepMedia: true };
  const normDisplay = (s) => Object.assign({}, DISPLAY_DEFAULT, s || {});

  function isInverted(s, host) {
    s = normDisplay(s);
    return s.mode === 'all' || (s.mode === 'sites' && s.sites.includes(host));
  }

  function displayCSS(s, host) {
    s = normDisplay(s);
    const on = isInverted(s, host);
    const f = [];
    if (on) f.push('invert(1) hue-rotate(180deg)');
    if (s.brightness !== 100) f.push('brightness(' + s.brightness + '%)');
    if (s.contrast !== 100) f.push('contrast(' + s.contrast + '%)');
    if (s.sepia > 0) f.push('sepia(' + s.sepia + '%)');
    if (!f.length) return '';
    let css = 'html{filter:' + f.join(' ') + ' !important;' + (on ? 'background:#fff;' : '') + '}';
    if (on && s.keepMedia) {
      css += 'img,picture,video,canvas,[style*="background-image"]{filter:invert(1) hue-rotate(180deg) !important;}';
    }
    return css;
  }

  // ---- colors / themes ----
  function hex2rgb(h) {
    h = h.replace('#', '');
    if (h.length === 3) h = [...h].map((c) => c + c).join('');
    const n = parseInt(h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const rgb2hex = (r) => '#' + r.map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0')).join('');
  function mix(a, b, t) {
    const A = hex2rgb(a), B = hex2rgb(b);
    return rgb2hex(A.map((v, i) => v + (B[i] - v) * t));
  }
  function luminance(h) {
    const [r, g, b] = hex2rgb(h).map((v) => v / 255);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  function makeTheme(bg, fg, accent) {
    const dark = luminance(bg) < 0.5;
    const toolbar = mix(bg, fg, 0.06), field = mix(bg, fg, 0.12), border = mix(bg, fg, 0.25);
    const onAccent = luminance(accent) > 0.5 ? '#000000' : '#ffffff';
    return {
      colors: {
        frame: bg, frame_inactive: mix(bg, fg, 0.03),
        tab_background_text: fg, tab_selected: toolbar, tab_text: fg, tab_line: accent, tab_loading: accent,
        toolbar, toolbar_text: fg, bookmark_text: fg, icon_color: fg,
        toolbar_field: field, toolbar_field_text: fg, toolbar_field_border: border,
        toolbar_field_focus: field, toolbar_field_text_focus: fg,
        toolbar_field_highlight: accent, toolbar_field_highlight_text: onAccent,
        toolbar_top_separator: border, toolbar_bottom_separator: border,
        button_background_hover: mix(toolbar, fg, 0.12), button_background_active: mix(toolbar, fg, 0.2),
        popup: toolbar, popup_text: fg, popup_border: border, popup_highlight: accent, popup_highlight_text: onAccent,
        sidebar: bg, sidebar_text: fg, sidebar_border: border,
        ntp_background: bg, ntp_text: fg, input_background: field, input_color: fg,
      },
      properties: { color_scheme: dark ? 'dark' : 'light' },
    };
  }

  const THEMES = [
    { id: 'light', name: 'Light', bg: '#f0f0f4', fg: '#15141a', accent: '#0060df' },
    { id: 'dark', name: 'Dark', bg: '#1c1b22', fg: '#fbfbfe', accent: '#00ddff' },
    { id: 'midnight', name: 'Midnight', bg: '#0b1020', fg: '#e6edf7', accent: '#7aa2ff' },
    { id: 'nord', name: 'Nord', bg: '#2e3440', fg: '#eceff4', accent: '#88c0d0' },
    { id: 'solarized-dark', name: 'Solarized Dark', bg: '#002b36', fg: '#93a1a1', accent: '#b58900' },
    { id: 'solarized-light', name: 'Solarized Light', bg: '#fdf6e3', fg: '#586e75', accent: '#268bd2' },
    { id: 'contrast', name: 'High contrast', bg: '#000000', fg: '#ffffff', accent: '#ffff00' },
  ];

  // ---- host helpers ----
  function hostFrom(v) {
    v = String(v || '').trim();
    try { return new URL(/^[a-z]+:\/\//i.test(v) ? v : 'https://' + v).hostname.replace(/^www\./, '').toLowerCase(); }
    catch (e) { return v.toLowerCase(); }
  }
  function hostMatches(entryHost, tabHost) {
    const a = hostFrom(entryHost), b = hostFrom(tabHost);
    return !!a && (a === b || b.endsWith('.' + a));
  }

  // ---- password generator ----
  function genPassword(len) {
    len = Math.max(8, Math.min(128, len || 20));
    const sets = ['abcdefghijkmnopqrstuvwxyz', 'ABCDEFGHJKLMNPQRSTUVWXYZ', '23456789', '!@#$%^&*-_=+?'];
    const all = sets.join('');
    const rnd = (n) => { // unbiased
      const max = Math.floor(0x100000000 / n) * n; const a = new Uint32Array(1);
      do { crypto.getRandomValues(a); } while (a[0] >= max);
      return a[0] % n;
    };
    for (;;) {
      let p = ''; for (let i = 0; i < len; i++) p += all[rnd(all.length)];
      if (sets.every((s) => [...p].some((c) => s.includes(c)))) return p;
    }
  }

  // ---- CSV ----
  function parseCSV(text) {
    const rows = []; let row = [], cur = '', q = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (q) {
        if (c === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += c;
      } else if (c === '"') q = true;
      else if (c === ',') { row.push(cur); cur = ''; }
      else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cur); rows.push(row); row = []; cur = ''; }
      else cur += c;
    }
    if (cur || row.length) { row.push(cur); rows.push(row); }
    return rows.filter((r) => r.some((x) => x !== ''));
  }
  function toCSV(rows) {
    return rows.map((r) => r.map((v) => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"').join(',')).join('\r\n') + '\r\n';
  }
  // Works with Firefox (url,username,password) and Chrome/Edge (name,url,username,password,note) exports.
  function loginsFromCSV(rows) {
    if (!rows.length) return [];
    const head = rows[0].map((h) => h.trim().toLowerCase());
    const ix = (...names) => head.findIndex((h) => names.includes(h));
    const iu = ix('url', 'origin', 'hostname', 'website', 'login_uri'), iun = ix('username', 'login', 'login_username', 'user');
    const ip = ix('password', 'login_password'), inn = ix('note', 'notes');
    if (iu < 0 || ip < 0) throw new Error('CSV needs url and password columns');
    return rows.slice(1).filter((r) => r[iu] && r[ip]).map((r) => ({
      host: hostFrom(r[iu]), username: iun >= 0 ? r[iun] : '', password: r[ip], notes: inn >= 0 ? r[inn] : '',
    }));
  }

  return { DISPLAY_DEFAULT, normDisplay, isInverted, displayCSS, makeTheme, THEMES, mix, luminance,
           hostFrom, hostMatches, genPassword, parseCSV, toCSV, loginsFromCSV };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = VFCommon;
