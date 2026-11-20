/* Pair devices: show a QR for another device to scan, or scan one to join an existing account. */
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

let mode = location.hash === '#scan' ? 'scan' : 'show';
let stream = null, scanning = false, hideTimer = null;

function stopCamera() {
  scanning = false;
  if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
}

async function render() {
  stopCamera(); clearInterval(hideTimer);
  const s = await send('status');
  const tabs = h('div', { class: 'tabs' },
    h('button', { class: mode === 'show' ? 'on' : '', onclick: () => { mode = 'show'; render(); } }, 'Show QR (this device)'),
    h('button', { class: mode === 'scan' ? 'on' : '', onclick: () => { mode = 'scan'; render(); } }, 'Scan QR (new device)'));
  app.replaceChildren(h('h1', {}, 'Pair devices'),
    h('p', { class: 'muted' }, 'Move your user name, secret key and server address to another device without typing the key.'),
    tabs, mode === 'show' ? viewShow(s) : viewScan(s));
}

// ---------- show ----------
function drawQR(canvas, text) {
  const qr = qrcode(0, 'M'); qr.addData(text); qr.make();
  const n = qr.getModuleCount(), quiet = 4, scale = Math.max(2, Math.floor(480 / (n + quiet * 2)));
  const size = (n + quiet * 2) * scale;
  canvas.width = canvas.height = size;
  const g = canvas.getContext('2d');
  g.fillStyle = '#fff'; g.fillRect(0, 0, size, size); g.fillStyle = '#000';
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) g.fillRect((c + quiet) * scale, (r + quiet) * scale, scale, scale);
}

function viewShow(s) {
  if (!s.setup) return h('div', { class: 'card' }, 'This device is not set up yet. Create a vault from the toolbar icon first, or scan a QR from another device.');
  if (!s.unlocked) return h('div', { class: 'card' }, 'Unlock IUK Browser from the toolbar icon first, then come back here.');
  const secret = h('input', { type: 'password', placeholder: 'Type your secret connectivity key again', autocomplete: 'off' });
  const msg = h('div'); const box = h('div');
  const go = h('button', { class: 'primary', onclick: async () => {
    go.disabled = true; note(msg, 'muted', 'Checking key (takes a moment)…');
    try {
      const code = await send('pairingPayload', { secret: secret.value });
      secret.value = ''; msg.textContent = '';
      const canvas = h('canvas', { class: 'qr', role: 'img', 'aria-label': 'Pairing QR code' });
      drawQR(canvas, code);
      let left = 90; const timer = h('div', { class: 'muted' }, 'Hides in ' + left + ' s');
      hideTimer = setInterval(() => { left--; timer.textContent = 'Hides in ' + left + ' s'; if (left <= 0) { clearInterval(hideTimer); box.replaceChildren(h('div', { class: 'muted' }, 'QR hidden.')); go.disabled = false; } }, 1000);
      box.replaceChildren(h('div', { class: 'qrbox' }, canvas, timer,
        h('div', { class: 'row' },
          h('button', { onclick: () => { clearInterval(hideTimer); box.replaceChildren(h('div', { class: 'muted' }, 'QR hidden.')); go.disabled = false; } }, 'Hide now'),
          h('button', { onclick: async () => { await navigator.clipboard.writeText(code); note(msg, 'ok', 'Pairing code copied. Treat it like your key.'); } }, 'Copy code instead'))));
    } catch (e) { go.disabled = false; note(msg, 'err', e.message); }
  } }, 'Show pairing QR');
  return h('div', {},
    h('div', { class: 'warn' }, 'The QR contains your secret key. Anyone who scans it, or sees a photo or screenshot of it, gets full access to your synced bookmarks and passwords. Show it only to your own second device.'),
    h('p', {}, 'On the new device open IUK Browser, choose ', h('b', {}, 'Scan pairing QR'), ', and point its camera at this screen.'),
    secret, h('div', { class: 'row' }, go), msg, box);
}

// ---------- scan ----------
function viewScan(s) {
  if (s.setup) return h('div', { class: 'card' }, 'This device already has a vault. To pair it as a new device, use "Forget this device" in settings first (data on the server stays).');
  const status = h('div', { class: 'muted' });
  const confirmBox = h('div');
  const video = h('video', { playsinline: true, muted: true, hidden: true });
  const canvas = document.createElement('canvas');

  function offer(text) {
    let p;
    try { p = VFCommon.decodePairing(text); } catch (e) { note(status, 'err', e.message); return false; }
    stopCamera(); video.hidden = true;
    const out = h('div');
    const join = h('button', { class: 'primary', onclick: async () => {
      join.disabled = true; note(out, 'muted', 'Joining (derives the key, takes a moment)…');
      try { await send('setup', { username: p.username, secret: p.secret, server: p.server }); confirmBox.replaceChildren(h('div', { class: 'card ok' }, 'Paired. Your bookmarks and passwords are syncing. You can close this tab.')); }
      catch (e) { join.disabled = false; note(out, 'err', e.message); }
    } }, 'Join this account');
    confirmBox.replaceChildren(h('div', { class: 'card' },
      h('div', {}, 'Join account ', h('b', {}, p.username), p.server ? [' on ', h('b', {}, p.server)] : ' (no sync server in the code)', '?'),
      h('div', { class: 'row' }, join, h('button', { onclick: () => { confirmBox.replaceChildren(); status.textContent = ''; } }, 'Cancel')), out));
    status.textContent = '';
    return true;
  }

  function decodeImageData(img) {
    const code = jsQR(img.data, img.width, img.height, { inversionAttempts: 'attemptBoth' });
    return code && code.data;
  }

  async function startCamera() {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
    } catch (e) { return note(status, 'err', 'Camera not available (' + (e.name || 'error') + '). Choose an image or paste the code instead.'); }
    video.srcObject = stream; video.hidden = false; await video.play();
    note(status, 'muted', 'Point the camera at the QR code…');
    scanning = true;
    const g = canvas.getContext('2d', { willReadFrequently: true });
    const tick = () => {
      if (!scanning) return;
      if (video.readyState >= 2 && video.videoWidth) {
        canvas.width = video.videoWidth; canvas.height = video.videoHeight;
        g.drawImage(video, 0, 0);
        const text = decodeImageData(g.getImageData(0, 0, canvas.width, canvas.height));
        if (text && text.startsWith(VFCommon.PAIR_PREFIX) && offer(text)) return;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  const file = h('input', { type: 'file', accept: 'image/*', hidden: true, onchange: async () => {
    try {
      const bmp = await createImageBitmap(file.files[0]);
      canvas.width = bmp.width; canvas.height = bmp.height;
      const g = canvas.getContext('2d', { willReadFrequently: true }); g.drawImage(bmp, 0, 0);
      const text = decodeImageData(g.getImageData(0, 0, canvas.width, canvas.height));
      if (!text) note(status, 'err', 'No QR code found in that image.'); else offer(text);
    } catch (e) { note(status, 'err', 'Could not read that image.'); }
    file.value = '';
  } });
  const paste = h('textarea', { rows: 3, placeholder: 'Or paste a pairing code (starts with IUKB1:)' });

  return h('div', {},
    h('div', { class: 'row' }, h('button', { class: 'primary', onclick: startCamera }, 'Start camera'), h('button', { onclick: () => file.click() }, 'Choose image…'), file),
    video, paste, h('div', { class: 'row' }, h('button', { onclick: () => offer(paste.value) }, 'Use pasted code')), status, confirmBox);
}

window.addEventListener('pagehide', stopCamera);
render();
