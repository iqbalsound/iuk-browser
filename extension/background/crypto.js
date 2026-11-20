/* Key derivation + authenticated encryption. Zero-knowledge: the sync server only ever sees `token` (a bearer
   secret) and ciphertext. The AES key and the token are independent halves of one KDF output, so knowing the
   token reveals nothing about the key.

   KDF versions (stored with the vault and in each synced document):
     'pbkdf2-v1'   PBKDF2-HMAC-SHA256, 600,000 iterations      (IUK Browser 1.0 and earlier; migrated on unlock)
     'argon2id-v2' Argon2id, 64 MiB, 3 passes, 1 lane         (IUK Browser 1.1+)                                */
var VFCrypto = (function () {
  const wc = (typeof crypto !== 'undefined' && crypto.subtle) ? crypto : require('node:crypto').webcrypto;
  const hw = (typeof hashwasm !== 'undefined') ? hashwasm : require('../vendor/argon2.umd.min.js');
  const enc = new TextEncoder(), dec = new TextDecoder();

  const KDF_LEGACY = 'pbkdf2-v1', KDF_LATEST = 'argon2id-v2';
  // Mutable so tests can lower the cost; never change these for real data.
  const PARAMS = {
    'pbkdf2-v1': { iterations: 600000 },
    'argon2id-v2': { memoryKiB: 65536, passes: 3, lanes: 1 },
  };

  function b64e(buf) {
    const b = new Uint8Array(buf); let s = '';
    for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
    return btoa(s);
  }
  const b64d = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const hex = (buf) => [...new Uint8Array(buf)].map((x) => x.toString(16).padStart(2, '0')).join('');
  const normUser = (u) => String(u).trim().toLowerCase();

  async function rawBits(kdf, username, secret) {
    if (kdf === KDF_LEGACY) {
      const salt = enc.encode('iuk-browser-v1|' + normUser(username));
      const base = await wc.subtle.importKey('raw', enc.encode(secret), 'PBKDF2', false, ['deriveBits']);
      return new Uint8Array(await wc.subtle.deriveBits(
        { name: 'PBKDF2', hash: 'SHA-256', salt, iterations: PARAMS[KDF_LEGACY].iterations }, base, 512));
    }
    if (kdf === KDF_LATEST) {
      const p = PARAMS[KDF_LATEST];
      // Deterministic 32-byte salt from the user name (no server-side salt exists in a zero-knowledge design).
      const salt = new Uint8Array(await wc.subtle.digest('SHA-256', enc.encode('iuk-browser-v2|' + normUser(username))));
      return hw.argon2id({ password: secret, salt, parallelism: p.lanes, iterations: p.passes, memorySize: p.memoryKiB, hashLength: 64, outputType: 'binary' });
    }
    throw new Error('Unknown key derivation: ' + kdf);
  }

  /** @returns {{key: CryptoKey, token: string, kdf: string}} AES key (non-extractable) and server bearer token */
  async function deriveKeys(username, secret, kdf) {
    kdf = kdf || KDF_LATEST;
    const bits = await rawBits(kdf, username, secret);
    const key = await wc.subtle.importKey('raw', bits.slice(0, 32), 'AES-GCM', false, ['encrypt', 'decrypt']);
    return { key, token: hex(bits.slice(32, 64)), kdf };
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

  return { KDF_LEGACY, KDF_LATEST, PARAMS, deriveKeys, encrypt, decrypt };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = VFCrypto;
