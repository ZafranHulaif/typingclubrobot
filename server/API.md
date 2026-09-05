# API kontrak backend TypingBot (v1)

Satu kontrak, dua implementasi:

- `local_server.py` - server lokal (dev/test/emergency, Python stdlib saja)
- `worker.js` - Cloudflare Worker (produksi, KV + R2, gratis)

Semua respons JSON UTF-8 kecuali `/api/download` dan `/admin`.

## Endpoint publik (dipakai aplikasi)

### `GET /api/latest`
Info rilis terbaru. `404` bila belum ada rilis.
```json
{"version": "2.8", "sha256": "<hex>", "size": 58300000,
 "notes": "perbaikan kecil", "released": "2026-08-27T10:00:00Z"}
```

### `POST /api/license/request`
Body: `{"mc": "XXXXX-XXXXX", "nickname": "Ucok", "app_version": "2.7"}`
Idempoten: mesin yang sudah approved langsung diberi token.
```json
{"status": "pending"}
{"status": "approved", "token": {"mc": "...", "exp": 1790000000, "sig": "<hex>"}}
```

### `GET /api/license/status?mc=XXXXX-XXXXX`
```json
{"status": "pending"}
{"status": "approved", "token": {"mc": "...", "exp": 1790000000, "sig": "<hex>"}}
{"status": "denied"}
{"status": "unknown"}
```

### `GET /api/download?t=<token b64>`
Token = base64(JSON token di atas). Stream binary exe.
`403` bila token tidak valid/kedaluwarsa.

## Token lisensi

- `exp` = unix detik, token berlaku 30 hari, diperpanjang otomatis setiap
  aplikasi berhasil mengecek status saat online.
- `sig` = Ed25519 atas string `v1|{mc}|{exp}` dengan private key server.
- Aplikasi memverifikasi token secara OFFLINE memakai public key yang
  ditanam di `net/license.py` (private key tidak pernah ada di exe).
- Sandaran lama: kunci HMAC manual (`_license_gen.py`) tetap diterima
  aplikasi, jadi lisensi lama tidak hangus saat migrasi.

## Endpoint pemilik

### `GET /admin?key=<ADMIN_KEY>`
Dashboard HTML (mobile-friendly): daftar mesin + tombol
Setujui / Tolak / Cabut / Tunggu.

### `POST /admin/action?key=<ADMIN_KEY>`
Form: `mc`, `act` (`approve`|`deny`|`revoke`|`pending`). Redirect balik.

### `POST /api/publish`
Header: `X-Admin-Key`, `X-Version`, `X-Notes`; body = binary exe mentah.
Unggah rilis baru. Respons: `{"ok": true, "sha256": "...", "size": N}`.

## Penyimpanan

| Data              | local_server        | Worker        |
| ----------------- | ------------------- | ------------- |
| mesin (status dsb)| `_store/machines.json` | KV `MACHINES` |
| metadata rilis    | `_store/release.json`  | KV `META`     |
| binary exe        | `_store/TypingBot.exe` | R2 `TypingBot.exe` |
| private key       | `_signing.json` (gitignore) | secret `SIGN_PRIV` (PKCS8 b64) |
| public key        | idem                | var `SIGN_PUB` (hex) |
