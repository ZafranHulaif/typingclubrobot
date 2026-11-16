# TypingBot Edisi Web (macOS / Linux / Android-Termux)

Mesin bot-nya **sama persis** dengan aplikasi Windows (`engine/`) — yang
Windows-saja cuma cangkang GUI ter-embed (WebView2). Edisi web menjalankan
mesin itu di browser Chromium mana pun yang ada di sistem, dan panel
kontrolnya jadi halaman web di `http://localhost:8765`.

Yang ADA di edisi web: Mulai/Berhenti/Jeda, kecepatan wpm, form login edclub
(mode headless), log langsung, deteksi level & pemulihan & game — semua logika
mesin.
Yang TIDAK ADA (tetap khusus aplikasi Windows): browser ter-embed di dalam
app, buku akun (multi-akun + tukar akun seklik), hotkey F9/F10/F11,
pembaruan otomatis.

## macOS / Linux

```bash
bash platforms/install.sh
```

Skrip itu: cek Python 3, `pip install playwright` (untuk jaringan CDP),
deteksi Chrome/Brave/Edge/Chromium terpasang, lalu jalankan bot dan buka
panel `http://localhost:8765`. Bot meluncurkan browsermu dengan **profil
khusus bot** (`~/.typingbot/chrome`) — login edclub sekali di jendela itu,
sesi menggantung di profil = mulai ulang tidak perlu login lagi.

Jalan manual (kalau mau atur sendiri):

```bash
python3 -m pip install playwright
python3 bot_web.py                 # panel di :8765, browser otomatis
python3 bot_web.py --headless      # tanpa jendela (server) - login via panel
python3 bot_web.py --browser "/usr/bin/chromium" --port 9000
python3 bot_web.py --cdp 9222      # tempel browser yang sudah jalan
```

## Android (Termux) — EKSPERIMEN

Dua jalur, keduanya butuh Termux (F-Droid build disarankan):

**Jalur A - headless di dalam Termux** (paling sederhana, berat di HP):

```bash
pkg install python glibc-runner git -y
bash platforms/install-termux.sh
python3 -m playwright install chromium   # unduh chromium (glibc)
python3 bot_web.py --headless
```

Panel buka di Chrome HP: `http://localhost:8765` (Termux jalan = bot hidup).
Catatan: chromium glibc di Termux butuh glibc-runner aktif; kalau gagal
jalankan `grun python3 bot_web.py --headless`.

**Jalur B - tempel Kiwi Browser yang sudah login** (lebih enteng):
Kiwi = Chromium dengan debugging jarak jauh. Aktifkan via `chrome://flags`
("Enable command line on non-rooted devices"), taruh
`--remote-debugging-port=9222` di `/data/local/tmp/kiwi-command-line`,
restart Kiwi, lalu jembatani socket-nya ke TCP untuk Termux:

```bash
pkg install socat -y
# cari nama socket: cat /proc/net/unix | grep -i devtools_remote
socat TCP-LISTEN:9222,reuseaddr,fork ABSTRACT-CONNECT:chrome_devtools_remote &
python3 bot_web.py --cdp 9222
```

Dua jalur Android belum diuji luas di berbagai HP — anggap beta, laporkan
log kalau mentok.

## CI

`.github/workflows/web.yml` menjalankan smoke (panel + status + chromium)
di ubuntu tiap rilis dan melampirkan `TypingBot-web-<versi>.zip` (paket
source siap jalan: bot_web.py + engine/ + paths.py + level_map.json) ke
halaman release.
