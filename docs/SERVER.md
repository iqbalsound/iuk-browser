# Sync relay

A single stdlib-only Python file, `server/iuk_relay.py`. It stores one **opaque encrypted blob per account**; it never sees
your key or any plaintext, and it is wire-compatible with the 1.x relay.

```bash
PORT=8787 HOST=127.0.0.1 DATA_DIR=/var/lib/iuk-relay python3 server/iuk_relay.py
```
Run it behind HTTPS (Caddy: `sync.example.com { reverse_proxy 127.0.0.1:8787 }`) and set `TRUST_PROXY=1`. A `Dockerfile` and a
hardened `iuk-relay.service` (systemd) are included.

## Second factor (optional, per account)
In the browser: Settings → Sync → *Second factor for the sync relay…* → Turn on, scan the QR with any authenticator app,
enter the code, and save the 8 recovery codes. From then on `/v1/blob` needs a session (12 h) obtained with a TOTP code or a
recovery code. A stolen sync token alone can no longer download the ciphertext; brute force is limited to 5 attempts per
10 minutes, a TOTP code cannot be replayed, and recovery codes work once. New devices and new sessions ask for a code.

## One-time device pairing
`PUT /v1/pair/<id>` (authenticated, needs a 2FA session when enabled) stores an encrypted pairing blob for 120 seconds, at most
3 pending per account, 4 KB max, **in memory only**. `GET /v1/pair/<id>` returns it **once** and deletes it; it needs no
account authentication because the 128-bit random id is the capability, and the blob is encrypted with a one-time key that
only the QR carries. `GET /v1/pair/<id>/status` (owner) tells the showing device whether it is still pending;
`DELETE /v1/pair/<id>` (owner) withdraws it.

## API (summary)
`GET|PUT|DELETE /v1/blob` (Bearer token, `If-Match` / `If-None-Match: *`), `GET /v1/2fa/status`, `POST /v1/2fa/enroll`,
`POST /v1/2fa/confirm`, `POST /v1/session`, `POST /v1/2fa/disable`, `PUT|GET|DELETE /v1/pair/<id>`, `GET /v1/pair/<id>/status`, `GET /health`.

Back up `DATA_DIR`; losing it loses only the server copy (devices keep their own data and re-upload on the next sync).
