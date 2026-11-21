# -*- coding: utf-8 -*-
"""Cek laporan bug baru dari worker -> tulis yang belum terbaca.

Dipakai task terjadwal T3: keluaran "TIDAK ADA BARU" kalau kosong,
kalau ada = cetak laporan lengkap (waktu/versi/akun/kategori/cerita).
State laporan terbaca = _lapor_seen.txt di root repo (gitignored).
"""
import io
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "_lapor_seen.txt")


def main():
    d = json.load(io.open(os.path.join(ROOT, "server", "_admin.json"),
                          encoding="utf-8"))
    url = d["url"].rstrip("/") + "/api/lapor-list"
    kunci = io.open(os.path.join(ROOT, "server", "_admin_key.txt"),
                    encoding="utf-8").read().strip()
    req = urllib.request.Request(url, headers={
        "X-Admin-Key": kunci,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "TypingBot-admin/1.0",
        "Accept": "application/json"})
    r = urllib.request.urlopen(req, timeout=20)
    body = json.loads(r.read().decode("utf-8"))

    sudah = set()
    if os.path.exists(STATE):
        sudah = {x.strip() for x in io.open(STATE, encoding="utf-8")
                 if x.strip()}

    baru = [x for x in body.get("detail", [])
            if str(x.get("ts")) not in sudah]
    if not baru:
        print("TIDAK ADA BARU")
        return

    for det in sorted(baru, key=lambda x: x.get("ts", 0)):
        ts = det.get("ts")
        isi = det.get("isi", "")
        print("=== LAPORAN BARU " + str(ts) + " ===")
        # cerita user = bagian antara CERITA USER dan LOG; log = ringkas
        potong = isi.split("=== CERITA USER ===")
        kepala = potong[0].strip()
        cerita = ""
        if len(potong) > 1:
            cerita = potong[1].split("=== LOG")[0].strip()
        print(kepala)
        if cerita:
            print("CERITA: " + cerita[:800])
        sudah.add(str(ts))

    io.open(STATE, "w", encoding="utf-8").write(
        "\n".join(sorted(sudah)) + "\n")


if __name__ == "__main__":
    main()
