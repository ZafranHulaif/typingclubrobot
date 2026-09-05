# Cara pasang backend TypingBot (panduan santai, ~15 menit)

Ada 3 kata Cloudflare yang akan kamu lihat, artinya cuma ini:

| Istilah       | Artinya sebenarnya                                          |
| ------------- | ----------------------------------------------------------- |
| Worker        | kode server kecil kamu, tinggal tempel-tempel               |
| KV            | "buku tulis" kecil untuk menyimpan daftar komputer temanmu |
| R2            | "flashdisk online" untuk menyimpan file TypingBot.exe      |

Semua gratis, tanpa kartu kredit. Kamu cuma buat akun sekali.

---

## LANGKAH 0 - jalankan penuntun (dia yang kasih nilai yang harus ditempel)

```
python server/setup.py
```

Dia akan buat kunci-kunci, lalu mencetak **4 nilai** + URL halaman
persetujuanmu. Layar itu tetap buka / foto dulu, langkah 2 pakai itu.

## LANGKAH 1 - bikin akun Cloudflare (2 menit)

1. Buka https://dash.cloudflare.com
2. Sign up (email + password). Pilih plan **Free** kalau ditanya.

## LANGKAH 2 - bikin Workernya (5 menit)

1. Menu kiri: **Workers & Pages** -> tombol **Create**
2. Pilih **Create Worker** -> nama: `typingbot-api` -> **Deploy**
3. Setelah jadi, klik **Edit code**
4. Hapus SEMUA kode bawaan di editor, tempel seluruh isi file
   `server/worker.js` (dari repo ini)
5. Klik **Save and Deploy** (kanan atas)
6. Catat URL Workermu, bentuknya:
   `https://typingbot-api.nama-kamu.workers.dev`

## LANGKAH 3 - isi 4 nilai dari LANGKAH 0 (5 menit)

Masih di halaman Worker, tab **Settings**:

1. **Variables and Secrets** -> **Add**:
   - Type **Variable**, name `SIGN_PUB`, value = nilai (1) dari LANGKAH 0
   - Type **Secret**, name `SIGN_PRIV`, value = nilai (2)
   - Type **Secret**, name `ADMIN_KEY`, value = nilai (3)
   - Type **Variable**, name `BASE`, value = URL Workermu dari LANGKAH 2
2. **Bindings** -> **Add** (tiga kali):
   - KV Namespace, variable name `MACHINES`,
     create namespace `typingbot-machines`
   - KV Namespace, variable name `META`, create namespace `typingbot-meta`
   - R2 Bucket, variable name `BUCKET`, create bucket `typingbot-releases`
3. Klik **Save and Deploy** sekali lagi.

## LANGKAH 4 - tes sambungan

Jalankan lagi `python server/setup.py`, tempel URL Worker saat ditanya.
Kalau tertulis **SAMBUTAN BERHASIL** (menjawab 404 = normal, belum ada
rilis), lanjut. Penuntun juga otomatis menanam kunci publik ke
`net/license.py` - **setelah itu build ulang TypingBot.exe** biar kuncinya
ikut:

```
python -m PyInstaller --onefile --windowed --name TypingBot ^
    --version-file version_info.txt --clean --noconfirm bot_gui.py
```

## LANGKAH 5 - unggah rilis pertama + bagikan

```
python server/publish.py dist/TypingBot.exe --version 2.7 --notes "awal"
```

Kirim `TypingBot.exe` ini ke temanmu **terakhir kalinya**. Mulai versi
berikutnya cukup `publish.py`, aplikasi mereka nawarin tombol perbarui.

**Bookmark di HP**: `{URL-Worker}/admin?key={ADMIN_KEY}`
Ini halaman persetujuanmu - teman buka app -> kamu buka bookmark ->
tap **Setujui**. Selesai.

---

## Uji sendiri tanpa Cloudflare

```
python server/local_server.py
```

Server yang sama persis jalan di laptopmu (http://127.0.0.1:8788).
Untuk mencobanya dari aplikasi: tulis `http://127.0.0.1:8788` ke file
`server_url.txt` di sebelah TypingBot.exe.

## Kalau macet

| Gejala | Cek |
| ------ | --- |
| "BELUM TERHUBUNG" saat tes | URL lengkap dengan `https://`? Worker sudah Save and Deploy? |
| Halaman admin "kunci admin salah" | `?key=...` di URL sama persis dengan ADMIN_KEY? |
| App bilang "server tidak dikonfigurasi" | `server_url.txt` ada di sebelah exe, isinya URL Worker |
| App bilang "belum disetujui" | mesinmu belum di-Setujui di halaman admin |
| Unduh pembaruan 403 | itu mesin belum pernah kamu setujui (token kedaluwarsa 30 hari) |
| Teman pindah laptop | statusnya di admin masih pakai kode mesin lama; mesin baru = minta setuju lagi |

## Catatan keamanan

- `server/_signing.json` dan `server/_admin.json` sudah di-gitignore.
  Salin keduanya ke vault privat (`typingclubrobot-secrets`).
- Lisensi lama (kunci manual WhatsApp) tetap jalan; mesin lama akan
  minta persetujuan sekali supaya bisa ikut pembaruan otomatis.
- Kalau Workermu mati/tak diisi kuota: app tetap jalan offline sampai
  30 hari sebelum koneksi sukses terakhir.
