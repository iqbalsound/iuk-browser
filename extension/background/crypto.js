/* Key derivation + authenticated encryption (WebCrypto). Zero-knowledge: the sync server only ever sees
   `token` (a bearer secret) and ciphertext. The AES key and the token are independent halves of one
   PBKDF2 output, so knowing the token reveals nothing about the key. */
var VFCrypto = (function () {
  const wc = (typeof crypto !== 'undefined' && crypto.subtle) ? crypto : require('node:crypto').webcrypto;
  const enc = new TextEncoder(), dec = new TextDecoder();
  const ITERATIONS = 600000; // OWASP guidance for PBKDF2-HMAC-SHA256

  function b64e(buf) {
    const b = new Uint8Array(buf); let s = '';
    for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
    return btoa(s);
  }
  const b64d = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const hex = (buf) => [...new Uint8Array(buf)].map((x) => x.toString(16).padStart(2, '0')).join('');

  async function deriveKeys(username, secret, iterations) {
    const salt = enc.encode('iuk-browser-v1|' + String(username).trim().toLowerCase());
    const base = await wc.subtle.importKey('raw', enc.encode(secret), 'PBKDF2', false, ['deriveBits']);
    const bits = new Uint8Array(await wc.subtle.deriveBits(
      { name: 'PBKDF2', hash: 'SHA-256', salt, iterations: iterations || ITERATIONS }, base, 512));
    const key = await wc.subtle.importKey('raw', bits.slice(0, 32), 'AES-GCM', false, ['encrypt', 'decrypt']);
    return { key, token: hex(bits.slice(32)) };
  }

  async function encrypt(key, obj) {
    const iv = wc.getRandomValues(new Uint8Array(12));
    const ct = await wc.subtle.encrypt({ name: 'AES-GCM', iv }, key, enc.encode(JSON.stringify(obj)));
    return 'v1.' + b64e(iv) + '.' + b64e(ct);
  }

  async function decrypt(key, s) {
    const [v, iv, ct] = String(s).trim().split('.');
    if (v !== 'v1' || !iv || !ct) throw new Error('Unrecognised data format');
    const pt = await wc.subtle.decrypt({ name: 'AES-GCM', iv: b64d(iv) }, key, b64d(ct));
    return JSON.parse(dec.decode(pt));
  }

  return { ITERATIONS, deriveKeys, encrypt, decrypt };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = VFCrypto;
