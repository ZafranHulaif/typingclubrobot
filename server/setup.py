"""Penuntun setup backend TypingBot - jalankan ini, dia yang bimbing.

Pakai:  python server/setup.py

Wizard ini (urutan):
  1. buat kunci tanda tangan (kalau belum ada)
  2. buat kunci admin (kalau belum ada)
  3. cetak 4 nilai yang harus ditempel ke Cloudflare (tinggal salin)
  4. tanya URL Worker kamu -> tes sambungan
  5. tanam kunci publik ke aplikasi (net/license.py) otomatis
  6. (opsional) unggah rilis pertama

Mode non-interaktif untuk tes otomatis:
  python server/setup.py --url http://127.0.0.1:8788 --no-bake --yes
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ADMIN_FILE = os.path.join(HERE, "_admin.json")
KEYS_FILE = os.path.join(HERE, "_signing.json")
LICENSE_PY = os.path.join(ROOT, "net", "license.py")

sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)


def garis():
    print("=" * 62)


def langkah(n, judul):
    garis()
    print(f"LANGKAH {n}: {judul}")
    garis()


def tanya(pertanyaan, default=""):
    try:
        jawab = input(f"{pertanyaan} ").strip()
    except EOFError:
        jawab = ""
    return jawab or default


def pastikan_kunci():
    langkah(1, "Kunci tanda tangan")
    if os.path.exists(KEYS_FILE):
        data = json.load(open(KEYS_FILE, encoding="utf-8"))
        print("Sudah ada (server/_signing.json) - lanjut.")
        return data
    from gen_keys import generate
    data = generate(KEYS_FILE)
    print("Dibuat: server/_signing.json")
    print("SALIN file ini ke vault privat kamu (penting, cuma ada sekali).")
    return data


def pastikan_admin():
    langkah(2, "Kunci admin (password halaman persetujuanmu)")
    if os.path.exists(ADMIN_FILE):
        data = json.load(open(ADMIN_FILE, encoding="utf-8"))
        print("Sudah ada (server/_admin.json) - lanjut.")
        return data
    import secrets
    data = {"url": "", "admin_key": secrets.token_hex(16)}
    with open(ADMIN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print("Dibuat: server/_admin.json")
    return data


def tampilkan_nilai(keys, admin):
    langkah(3, "Tempel 4 nilai ini ke Cloudflare (salin satu per satu)")
    print("""Kalau kamu belum bikin Workernya: buka
https://dash.cloudflare.com -> daftar/akun gratis ->
Compute -> Workers & Pages -> Create application (dashboard
lama: "Create") -> pilih Workers / Hello World ->
nama: typingbot-api -> Deploy -> Edit code (ikon </>) ->
hapus semua isi -> tempel isi server/worker.js -> Save and Deploy.

Lalu di Settings Worker kamu, buat yang ini:""")
    print(f"""
1) Variable  bernama SIGN_PUB  nilainya:
{keys['pub_hex']}

2) Secret    bernama SIGN_PRIV nilainya:
{keys['priv_pkcs8_b64']}

3) Secret    bernama ADMIN_KEY nilainya:
{admin['admin_key']}

4) Variable  bernama BASE nilainya:
https://typingbot-api.SUBDOMAIN-KAMU.workers.dev
   (URL Workermu sendiri; terlihat di halaman Worker ->
    Permissions/Domain atau setelah Deploy)

Juga butuh (Worker -> Settings -> Bindings -> Add -> KV namespace):
- KV binding  MACHINES -> namespace "typingbot-machines"
- KV binding  META     -> namespace "typingbot-meta"
(Namespace dibuat di halaman Workers KV -> tombol "Create instance".
R2/kartu kredit tidak diperlukan - exe disimpan di KV.)""")


def tes_sambungan(base, timeout=10):
    import urllib.error
    import urllib.request
    try:
        req = urllib.request.Request(
            base + "/api/latest",
            headers={"User-Agent": "TypingBot-setup/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, f"terhubung (status {r.status})"
    except urllib.error.HTTPError as e:
        return True, (f"terhubung (server menjawab {e.code}; "
                      "belum ada rilis = normal)")
    except Exception as e:
        return False, str(e)


def simpan_url(data, base):
    data["url"] = base.rstrip("/")
    with open(ADMIN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def tanam_pubkey(pub_hex):
    src = open(LICENSE_PY, encoding="utf-8").read()
    lama = "SERVER_PUBLIC_KEY_HEX = \"\""
    if lama not in src:
        return False
    src = src.replace(lama, f"SERVER_PUBLIC_KEY_HEX = \"{pub_hex}\"", 1)
    with open(LICENSE_PY, "w", encoding="utf-8") as f:
        f.write(src)
    return True


def rapikan_url(base):
    """Lengkapi skema kalau user tempel tanpa https:// (bug umum)."""
    base = (base or "").strip().rstrip("/")
    if not base:
        return base
    if "://" in base:
        return base
    lokal = base.startswith("127.0.0.1") or base.startswith("localhost")
    return ("http://" if lokal else "https://") + base


def tulis_server_url_txt(base):
    p = os.path.join(ROOT, "dist", "server_url.txt")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(base.rstrip("/") + "\n")
    print(f"ditulis: {p} (taruh file ini di sebelah TypingBot.exe)")


def tawarkan_publish(base, admin_key):
    exe = tanya("Unggah rilis sekarang? taruh path exe [dist/TypingBot.exe] "
                "atau kosongkan untuk skip:", "dist/TypingBot.exe")
    if exe == "dist/TypingBot.exe" and not os.path.exists(
            os.path.join(ROOT, exe)):
        print("skip (belum ada dist/TypingBot.exe).")
        return
    ver = tanya("Versi rilis [2.7]:", "2.7")
    notes = tanya("Catatan singkat [-]:", "")
    from publish import publish
    out = publish(os.path.join(ROOT, exe), ver, notes, base, admin_key)
    print("OK:", out["resp"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--no-bake", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()

    print("")
    print("   SETUP BACKEND TYPINGBOT - ikuti saja, pelan-pelan.")
    print("")
    keys = pastikan_kunci()
    admin = pastikan_admin()
    tampilkan_nilai(keys, admin)

    langkah(4, "Tes sambungan ke Worker kamu")
    base = rapikan_url(a.url or tanya(
        "Tempel URL Worker kamu (contoh: typingbot-api.xxx.workers.dev):",
        admin.get("url", "")))
    if not base:
        print("Belum ada URL - jalankan setup.py lagi setelah Workernya jadi.")
        return 1
    simpan_url(admin, base)
    ok, pesan = tes_sambungan(base)
    if ok:
        print("SAMBUTAN BERHASIL:", pesan)
    else:
        print(f"BELUM TERHUBUNG: {pesan}")
        print("""Cek umum:
- URL benar? (harus https://...workers.dev, tanpa /api di belakang)
- Worker sudah Save and Deploy?
- Binding KV/R2 dan 4 nilai di atas sudah disimpan di Settings?""")
        if not a.yes and tanya("Coba lagi setelah kamu bereskan? [y/n]:",
                              "n").lower() != "y":
            return 1
        ok, pesan = tes_sambungan(base)
        if not ok:
            print(f"Masih gagal ({pesan}) - buka server/DEPLOY.md bagian masalah.")
            return 1
        print("SAMBUTAN BERHASIL:", pesan)

    langkah(5, "Tanam kunci publik ke aplikasi")
    if a.no_bake:
        print("dilewati (--no-bake, mode tes)")
    elif tanam_pubkey(keys["pub_hex"]):
        print("net/license.py sudah berisi kunci publik server kamu.")
        print("Ingat: BUILD ULANG TypingBot.exe setelah ini supaya kunci "
              "ikut terbungkus.")
    else:
        print("net/license.py sudah tertanam sebelumnya - tidak diubah.")
    tulis_server_url_txt(base)

    langkah(6, "Selesai!")
    print(f"Halaman persetujuanmu (bookmark di HP):")
    print(f"  {base}/admin?key={admin['admin_key']}")
    print(f"Unggah versi baru kapan pun:")
    print(f"  python server/publish.py dist/TypingBot.exe --version X.Y")
    if not a.yes:
        tawarkan_publish(base, admin["admin_key"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
