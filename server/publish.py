"""Alat pemilik: unggah rilis baru ke backend (pengganti "kirim ulang exe").

Pakai:
  python server/publish.py dist/TypingBot.exe --version 2.8 \
      --notes "perbaikan X" [--url https://...worker.dev] [--key ADMIN_KEY]

URL dan kunci admin dibaca dari (berurutan): flag, env
TYPINGBOT_SERVER_URL / TYPINGBOT_ADMIN_KEY, file server/_admin.json
  {"url": "...", "admin_key": "..."} (di-gitignore).
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

UA = "TypingBot-publisher/1.0"


def _conf(args):
    url = args.url or os.environ.get("TYPINGBOT_SERVER_URL") or ""
    key = args.key or os.environ.get("TYPINGBOT_ADMIN_KEY") or ""
    try:
        with open(os.path.join(HERE, "_admin.json"), encoding="utf-8") as f:
            c = json.load(f)
        url = url or c.get("url", "")
        key = key or c.get("admin_key", "")
    except Exception:
        pass
    return url.rstrip("/"), key


def publish(exe_path, version, notes, url, key, timeout=600):
    # X-Notes = header HTTP: newline bikin putheader ValueError (live
    # 3.2.0). pipihkan jadi satu baris dgn pemisah bullet.
    notes = " | ".join(
        ln.strip() for ln in notes.splitlines() if ln.strip())
    h = hashlib.sha256()
    size = 0
    with open(exe_path, "rb") as f:
        while True:
            b = f.read(1 << 16)
            if not b:
                break
            h.update(b)
            size += len(b)
    req = urllib.request.Request(
        url + "/api/publish", method="POST",
        data=open(exe_path, "rb").read(),
        headers={"X-Admin-Key": key, "X-Version": version,
                 "X-Notes": notes, "Content-Type": "application/octet-stream",
                 "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return {"sha256": h.hexdigest(), "size": size, "resp": resp}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("--version", required=True)
    ap.add_argument("--notes", default="")
    ap.add_argument("--url", default="")
    ap.add_argument("--key", default="")
    a = ap.parse_args()
    url, key = _conf(a)
    if not url or not key:
        print("url/kunci admin belum diatur (lihat --help)")
        return 1
    if not os.path.exists(a.exe):
        print("file tidak ada:", a.exe)
        return 1
    # /api/download kini REDIRECT ke GitHub release asset - cek asset
    # v<versi> benar2 ada SEBELUM tayang, kalau tidak semua updater
    # dapat 404 (worker nol kerja berat sejak 3.2.0-followup).
    import urllib.error
    gh = ("https://github.com/ZafranHulaif/typingclubrobot/releases/"
          "download/v" + a.version + "/TypingBot.exe")
    cek = urllib.request.Request(gh, method="HEAD",
                                 headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(cek, timeout=30) as r:
            if r.status not in (200, 302):
                raise ValueError("status " + str(r.status))
        print("asset GitHub OK:", gh)
    except Exception as ex:
        print("GAGAL: asset GitHub belum ada (" + gh + ")")
        print("  -> jalankan dulu: gh release create v" + a.version,
              a.exe, "--title v" + a.version, "--notes ...")
        print("  alasan:", ex)
        return 1
    out = publish(a.exe, a.version, a.notes, url, key)
    print("terunggah:", a.version, out["size"], "byte")
    print("sha256 lokal :", out["sha256"])
    print("sha256 server:", out["resp"].get("sha256"))
    if out["resp"].get("sha256") != out["sha256"]:
        print("PERINGATAN: hash tidak cocok!")
        return 1
    print("OK - aplikasi temanmu akan menawarkan pembaruan saat mulai.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
