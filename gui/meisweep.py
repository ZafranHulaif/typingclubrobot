# -*- coding: utf-8 -*-
"""Bersih-bersih sisa ekstraksi PyInstaller onefile (folder _MEIxxx di
%TEMP%).

Bootloader onefile menghapus folder _MEI miliknya HANYA saat exit
bersih. taskkill /F (build agent), crash, mati listrik = folder
tertinggal (~180 MB per kejadian - live: 74 folder = 13.7 GB memenuhi
C: sampai user hapus manual). Sweep ini dipanggil saat app start dan
saat exit bersih: sisa basi dibuang otomatis, numpuknya berhenti.

AMAN utk instance lain yang masih jalan: setiap kandidat diuji dulu -
SEMUA .dll/.pyd di dalamnya harus bisa dibuka exclusive. Satu saja
yang terkunci (= modul sudah dimuat proses lain) -> folder itu
DILEWATI UTUH, tidak ada penghapusan sebagian."""
import os
import shutil
import sys
import tempfile
import time


def _semua_bisa_lock(path):
    """True kalau tidak ada satu pun file .dll/.pyd/.exe di folder yang
    terkunci (semua bisa dibuka r+b = tidak ada yang dimuat proses)."""
    try:
        for akar, _dirs, files in os.walk(path):
            for nama in files:
                if nama.lower().endswith((".dll", ".pyd", ".exe")):
                    try:
                        with open(os.path.join(akar, nama), "r+b"):
                            pass
                    except OSError:
                        return False
    except OSError:
        return False
    return True


HASIL_TERAKHIR = (0, 0.0)   # hasil sweep panggilan terakhir (n, MB)


def sweep_mei(log=None, min_age_s=0.0):
    """Hapus folder _MEI* basi di %TEMP%. Return (jumlah, mega-bait).

    min_age_s: lewati folder lebih muda dari ini (0 = langsung; guard
    utamanya tetap uji-lock, usia cuma lapis ekstra utk race saat dua
    instance boot bersamaan)."""
    n, mb = 0, 0.0
    try:
        tmp = os.environ.get("TEMP") or tempfile.gettempdir()
        milik = os.path.normcase(os.path.normpath(
            getattr(sys, "_MEIPASS", "") or os.sep))
        sekarang = time.time()
        for nama in os.listdir(tmp):
            if not nama.startswith("_MEI"):
                continue
            p = os.path.join(tmp, nama)
            if not os.path.isdir(p):
                continue
            if milik != os.sep and \
                    os.path.normcase(os.path.normpath(p)) == milik:
                continue      # milik sendiri - bootloader yang bereskan
            try:
                if sekarang - os.path.getmtime(p) < min_age_s:
                    continue
                if not _semua_bisa_lock(p):
                    continue   # masih dipakai instance lain - utuhkan
                ukuran = 0
                for akar, _d, files in os.walk(p):
                    for f2 in files:
                        try:
                            ukuran += os.path.getsize(
                                os.path.join(akar, f2))
                        except OSError:
                            pass
                shutil.rmtree(p, ignore_errors=True)
                if not os.path.exists(p):
                    n += 1
                    mb += ukuran / (1 << 20)
            except OSError:
                continue
    except Exception:
        pass
    global HASIL_TERAKHIR
    HASIL_TERAKHIR = (n, mb)
    if n and log:
        try:
            log(f"[BERSIH] {n} folder sisa update dibuang "
                f"({mb:.0f} MB) dari Temp.")
        except Exception:
            pass
    return n, mb
