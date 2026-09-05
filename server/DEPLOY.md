# Panduan deploy backend TypingBot (sekali saja, ~15 menit)

Semua tier gratis Cloudflare: Worker + KV + R2. Tanpa kartu kredit.

## 0. Punya akun Cloudflare
Daftar di https://dash.cloudflare.com (gratis).

## 1. Generate kunci
```
python server/gen_keys.py
```
Output `server/_signing.json` (JANGAN di-commit; salin ke vault privat).
Catat `pub_hex` - nanti ditanam ke aplikasi (langkah 4) dan var Worker.

## 2. Buat KV, R2, dan Worker
Dashboard Cloudflare:
- **Workers & Pages -> KV -> Create namespace** -> nama `typingbot-machines`
  (nanti di-bind sebagai `MACHINES`), buat satu lagi `typingbot-meta`
  (bind `META`).
- **R2 -> Create bucket** -> nama `typingbot-releases` (bind `BUCKET`).
- **Workers & Pages -> Create -> Worker** -> nama `typingbot-api`, Deploy,
  lalu Edit code: tempel isi `server/worker.js`, Save and Deploy.

Cara cepat lewat wrangler (opsional):
```
npm install -g wrangler && wrangler login
wrangler kv namespace create MACHINES
wrangler kv namespace create META
wrangler r2 bucket create typingbot-releases
wrangler deploy
```

## 3. Set binding + secrets Worker
Settings Worker:
- Binding KV: `MACHINES`, `META` (pilih namespace dari langkah 2).
- Binding R2: `BUCKET` (pilih bucket).
- Variabel `SIGN_PUB` = nilai `pub_hex` dari langkah 1.
- Variabel `BASE` = `https://typingbot-api.<subdomain-mu>.workers.dev`
  (URL Worker; terlihat setelah deploy).
- Secret `SIGN_PRIV` = nilai `priv_pkcs8_b64` dari langkah 1.
- Secret `ADMIN_KEY` = hasil
  `python -c "import secrets;print(secrets.token_hex(16))"`.

Simpan URL + ADMIN_KEY ke `server/_admin.json` (gitignore):
```json
{"url": "https://typingbot-api.xxx.workers.dev", "admin_key": "..."}
```
Bookmark di HP: `https://.../admin?key=<ADMIN_KEY>` <- halaman persetujuan.

## 4. Arahkan aplikasi ke Worker
Dua cara (salah satu):
- Tulis file `server_url.txt` berisi URL Worker, taruh di sebelah TypingBot.exe
  (bisa diganti tanpa build ulang), atau
- Ubah `DEFAULT_BASE_URL` di `net/api.py` lalu build ulang (lebih rapi).
Untuk verifikasi offline: tanam `pub_hex` di `SERVER_PUBLIC_KEY_HEX`
(`net/license.py`). Selama masih kosong, klien dev otomatis memakai
`server/_signing.json` lokal.

## 5. Unggah rilis pertama
```
python -m PyInstaller --onefile --windowed --name TypingBot \
    --version-file version_info.txt --clean --noconfirm bot_gui.py
python server/publish.py dist/TypingBot.exe --version 2.7 --notes "awal"
```

## 6. Ujicoba
- Jalankan exe di komputer lain -> muncul dialog nickname -> kirim.
- Buka bookmark admin di HP -> mesin muncul "pending" -> Setujui.
- Dialog berubah "disetujui", tombol Start hidup.
- Publish versi 2.8 -> start aplikasi -> muncul tombol perbarui -> tap.

## Catatan
- Lisensi lama (kunci manual) tetap valid - mesin lama hanya perlu
  disetujui sekali bila ingin bisa mengunduh pembaruan (server memberi
  token hanya ke mesin yang disetujui).
- Bila Worker mati: aplikasi tetap jalan offline sampai 30 hari.
- Semua operasi pemilik: halaman /admin + `server/publish.py`.
- Server lokal (`server/local_server.py`) memakai kontrak yang sama -
  berguna untuk tes tanpa Cloudflare.
