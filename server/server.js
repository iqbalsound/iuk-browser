#!/usr/bin/env node
/* IUK Browser relay: stores ONE opaque encrypted blob per sync token. Zero dependencies.
   It never sees the secret key or plaintext. Put it behind HTTPS (Caddy/nginx) when exposed to the internet.
   Env: PORT (8787), HOST (127.0.0.1), DATA_DIR (./data), TRUST_PROXY=1 to use X-Forwarded-For for rate limits. */
'use strict';
const http = require('http'), fs = require('fs'), path = require('path'), crypto = require('crypto');

const MAX_BODY = 5 * 1024 * 1024;
const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');

function createServer({ dataDir, rateLimit = 120, trustProxy = false }) {
  fs.mkdirSync(dataDir, { recursive: true });
  const hits = new Map();
  const limited = (ip) => {
    const now = Date.now(), list = (hits.get(ip) || []).filter((t) => now - t < 60000);
    list.push(now); hits.set(ip, list); return list.length > rateLimit;
  };
  setInterval(() => { const now = Date.now(); for (const [k, v] of hits) if (!v.some((t) => now - t < 60000)) hits.delete(k); }, 60000).unref();

  return http.createServer((req, res) => {
    const send = (code, body, headers) => { res.writeHead(code, Object.assign({ 'Content-Type': 'text/plain', 'Cache-Control': 'no-store' }, headers)); res.end(body || ''); };
    const ip = (trustProxy && String(req.headers['x-forwarded-for'] || '').split(',')[0].trim()) || req.socket.remoteAddress;
    if (req.url === '/health') return send(200, 'ok');
    if (limited(ip)) return send(429, 'Too many requests');
    if (req.url !== '/v1/blob') return send(404, 'Not found');
    const m = /^Bearer ([0-9a-f]{64})$/.exec(req.headers.authorization || '');
    if (!m) return send(401, 'Unauthorized');
    const file = path.join(dataDir, sha(m[1]) + '.blob');
    const current = fs.existsSync(file) ? fs.readFileSync(file) : null;
    const etag = (buf) => '"' + sha(buf).slice(0, 32) + '"';

    if (req.method === 'GET') {
      if (!current) return send(404, 'No data');
      return send(200, current, { ETag: etag(current) });
    }
    if (req.method === 'PUT') {
      const chunks = []; let size = 0, dead = false;
      req.on('data', (c) => { size += c.length; if (size > MAX_BODY) { dead = true; send(413, 'Too large'); req.destroy(); } else chunks.push(c); });
      req.on('end', () => {
        if (dead) return;
        const ifMatch = req.headers['if-match'], ifNone = req.headers['if-none-match'];
        if (!ifMatch && ifNone !== '*') return send(428, 'Precondition required');
        if (ifNone === '*' && current) return send(412, 'Already exists');
        if (ifMatch && (!current || ifMatch !== etag(current))) return send(412, 'Version mismatch');
        const body = Buffer.concat(chunks);
        if (!/^v1\.[A-Za-z0-9+/=]+\.[A-Za-z0-9+/=]+$/.test(body.toString('utf8').trim())) return send(400, 'Unexpected payload');
        const tmp = file + '.tmp'; fs.writeFileSync(tmp, body); fs.renameSync(tmp, file);
        return send(200, 'ok', { ETag: etag(body) });
      });
      return;
    }
    return send(405, 'Method not allowed');
  });
}

if (require.main === module) {
  const port = +process.env.PORT || 8787, host = process.env.HOST || '127.0.0.1';
  createServer({ dataDir: process.env.DATA_DIR || path.join(__dirname, 'data'), trustProxy: process.env.TRUST_PROXY === '1' })
    .listen(port, host, () => console.log('IUK Browser relay listening on http://' + host + ':' + port));
}
module.exports = { createServer };
