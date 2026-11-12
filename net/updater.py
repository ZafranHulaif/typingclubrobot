"""Pembaruan mandiri: cek versi, unduh, verifikasi hash, tukar exe.

Tukar exe hanya berlaku untuk hasil build PyInstaller (frozen); saat
dijalankan dari sumber, file baru diunduh dan user mengganti manual.
"""

import hashlib
import json
import os
import re
import subprocess
import sys

from . import api
from .license import download_param

NEW_SUFFIX = ".new.exe"
CMD_NAME = "_update.cmd"
PENDING_NAME = "update_pending.json"
OLD_SUFFIX = ".lama.exe"


class UpdateCancelled(Exception):
    """Unduhan pembaruan dibatalkan user dari dialog."""


def parse_version(s):
    bagian = []
    for x in str(s).strip().split("."):
        try:
            bagian.append(int(x))
        except ValueError:
            break
    return tuple(bagian or (0,))


def is_newer(remote, local):
    a, b = parse_version(remote), parse_version(local)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def check(app_version):
    """Info rilis baru (dict) bila ada dan lebih baru, selain itu None."""
    try:
        info = api.fetch_latest()
    except api.Unreachable:
        return None
    if not info or not info.get("version"):
        return None
    if not is_newer(info["version"], app_version):
        return None
    return info


def download(info, tok, new_path, progress_cb=None):
    """Unduh rilis ke new_path (bukan exe aktif!); raise bila hash beda.

    Workers menghapus Content-Length pada respons stream -> total dari
    info['size'] dipakai sebagai cadangan supaya % tetap tampil.
    progress_cb yang mengembalikan False membatalkan unduh
    (raise UpdateCancelled, file .part dibersihkan).
    """
    url = "/api/download?t=" + download_param(tok)

    def prog(got, total, _cb=progress_cb):
        if _cb:
            if _cb(got, total or info.get("size")) is False:
                raise api.Cancelled()

    try:
        digest = api.http_download(url, new_path, prog)
    except api.Cancelled:
        raise UpdateCancelled() from None
    if info.get("sha256") and digest != info["sha256"]:
        try:
            os.remove(new_path)
        except Exception:
            pass
        raise ValueError("hash unduhan tidak cocok (file korup/diubah)")
    return digest


def apply_update_and_restart(program_path):
    """Tulis _update.cmd, jalankan terpisah, lalu aplikasi harus keluar.

    Return True bila proses tukar sudah berjalan (pemanggil wajib
    menutup aplikasi). Hanya untuk frozen exe.
    """
    if not getattr(sys, "frozen", False):
        return False
    folder = os.path.dirname(os.path.abspath(program_path))
    nama = os.path.basename(program_path)
    cmd = os.path.join(folder, CMD_NAME)
    # ONEFILE = DUA proses: parent bootloader + child python. os.getpid()
    # = CHILD; PARENT yang memegang handle exe. Dulu cuma child yang
    # ditembak -> parent hidup terus -> ren gagal 90x -> exit /b 1 TANPA
    # meluncurkan apa pun = 'mulai ulang tidak menjalankan aplikasi'
    # (keluhan live 12 Nov 2026, update 3.2.7 -> 3.2.9).
    try:
        pid_parent = str(os.getppid())
    except Exception:
        pid_parent = "0"
    isi = (
        "@echo off\r\n"
        "setlocal\r\n"
        'set EXE="%~dp0' + nama + '"\r\n'
        'set NEW="%~dp0' + nama + NEW_SUFFIX + '"\r\n'
        'set OLD="' + nama + OLD_SUFFIX + '"\r\n'
        "set /a N=0\r\n"
        ":ganti\r\n"
        # ping, bukan timeout: timeout butuh konsol nyata - dulu cmd
        # membuka jendela terminal sebentar (membingungkan user awam)
        "ping -n 2 127.0.0.1 >nul\r\n"
        # REN dulu, JANGAN del: exe yang lagi jalan boleh di-RENAME
        # (delete tidak) - dan kalau move sesudahnya gagal kita tinggal
        # balikkan. Dulu del sukses lalu move gagal (AV memindai file
        # baru 78 MB) = TANPA exe sama sekali = "app won't start"
        # (keluhan live: teman user 11 Nov 2026).
        'ren "%EXE%" "%OLD%" >nul 2>&1\r\n'
        'if not exist "%EXE%" goto pasang\r\n'
        "set /a N+=1\r\n"
        # ~15 dtk masih terkunci: tembak CHILD (pid pemanggil), PARENT
        # bootloader (pemegang handle exe - lihat catatan atas), dan
        # SEMUA image se-nama utk instance lain. GEQ, bukan equ: ulang
        # tiap putaran - dulu equ 15 sekali saja, parent kadang baru
        # mati setelah itu dan 75 percobaan ren sisanya sia-sia.
        "if %N% geq 15 taskkill /f /pid " + str(os.getpid()) + " >nul 2>&1\r\n"
        "if %N% geq 15 taskkill /f /pid " + pid_parent + " >nul 2>&1\r\n"
        "if %N% geq 15 taskkill /f /im \"" + nama + "\" >nul 2>&1\r\n"
        "if %N% lss 90 goto ganti\r\n"
        # GAGAL TOTAL: jangan pernah mati diam - luncurkan exe lama
        # balik (pop_pending di app start akan menyelesaikan swap saat
        # lock sudah hilang). explorer, bukan start: start dari cmd
        # ditolak lapisan keamanan Windows (lihat :tunggu_proses).
        'if exist "%EXE%" explorer "%EXE%"\r\n'
        "exit /b 1\r\n"
        ":pasang\r\n"
        'if not exist "%NEW%" goto gulung\r\n'
        'move /y "%NEW%" "%EXE%" >nul 2>&1\r\n'
        'if exist "%EXE%" goto tunggu_proses\r\n'
        # AV masih memegang file baru - coba lagi sampai 15x
        "set /a N=0\r\n"
        ":coba\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        'move /y "%NEW%" "%EXE%" >nul 2>&1\r\n'
        'if exist "%EXE%" goto tunggu_proses\r\n'
        "set /a N+=1\r\n"
        "if %N% lss 15 goto coba\r\n"
        ":gulung\r\n"
        # ROLLBACK: balikkan exe lama - JANGAN PERNAH tinggal tanpa exe
        'ren "%OLD%" "' + nama + '" >nul 2>&1\r\n'
        # dan pastikan aplikasi HIDUP balik (dulu exit 1 diam-diam =
        # 'mulai ulang tidak menjalankan aplikasi', keluhan live)
        'if exist "%EXE%" explorer "%EXE%"\r\n'
        "exit /b 1\r\n"
        ":tunggu_proses\r\n"
        "del /f /q \"%OLD%\" >nul 2>&1\r\n"
        "set /a T=0\r\n"
        ":tunggu2\r\n"
        # proses lama harus benar2 keluar sebelum versi baru diluncurkan
        "tasklist /fi \"imagename eq " + nama + "\" | find /i \"" + nama
        + "\" >nul\r\n"
        "if not errorlevel 1 ping -n 2 127.0.0.1 >nul\r\n"
        "if not errorlevel 1 set /a T+=1\r\n"
        "if not errorlevel 1 if %T% lss 30 goto tunggu2\r\n"
        # luncurkan lewat explorer = seperti klik ganda user; 'start'
        # dari cmd menjadikan cmd orang tua proses dan ditolak lapisan
        # keamanan Windows ("security validation failure")
        'if exist "%EXE%" explorer "%EXE%"\r\n'
        'del /f /q "%~f0" >nul 2>&1\r\n'
    )
    with open(cmd, "w", encoding="ascii", newline="") as f:
        f.write(isi)
    # CREATE_NO_WINDOW: cmd jalan tersembunyi (dulu DETACHED_PROCESS
    # malah membuat cmd membuka konsol sendiri -> layar terminal
    # berkedip saat pembaruan)
    # PANGGIL DGN JALUR ABSOLUT - jangan nama telanjang: env var security
    # NoDefaultCurrentDirectoryInExePath (diwarisi app kalau diluncurkan
    # dari shell tertentu - terbukti live 12 Nov 2026) membuat cmd
    # MENOLAK menjalankan batch dari cwd-nya sendiri: 'is not recognized'
    # - skrip update TAK PERNAH jalan, app keluar tanpa lanjutan
    # (keluhan user: 'mulai ulang tidak menjalankan aplikasi').
    subprocess.Popen(["cmd", "/c", cmd], cwd=folder,
                     creationflags=0x08000000, close_fds=True)
    return True


# -------------------------------------------------- terpasang saat mulai
# User boleh menolak mulai ulang: unduhan yang sudah sah dicatat di
# update_pending.json; saat aplikasi DIBUKA LAGI, exe lama ditukar
# sebelum GUI muncul lalu versi baru dijalankan.


def _pending_path(program_path):
    return os.path.join(os.path.dirname(os.path.abspath(program_path)),
                        PENDING_NAME)


def stage_pending(program_path, info):
    """Catat unduhan .new.exe yang sudah terverifikasi siap dipasang."""
    with open(_pending_path(program_path), "w", encoding="utf-8") as f:
        json.dump({"version": info.get("version"),
                   "sha256": info.get("sha256")}, f)


def pending_info(program_path):
    try:
        with open(_pending_path(program_path), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def clear_pending(program_path):
    for p in (_pending_path(program_path), program_path + NEW_SUFFIX,
              program_path + OLD_SUFFIX):
        try:
            os.remove(p)
        except Exception:
            pass


def _ver_tuple(v):
    """'3.3.5' -> (3, 3, 5); string kotor aman (non-digit dibuang)."""
    try:
        return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3]) or (0,)
    except Exception:
        return (0,)


def pop_pending(program_path):
    """Dipanggil SEBELUM GUI saat aplikasi mulai.

    True = proses tukar sedang berjalan (pemanggil wajib keluar segera;
    script kemudian menjalankan versi baru). Marker/unduhan basi
    (hilang, hash tidak cocok, atau VERSI LEBIH LAMA dari yang jalan)
    dibersihkan diam-diam.
    """
    info = pending_info(program_path)
    if not info:
        return False
    baru = program_path + NEW_SUFFIX
    if not os.path.exists(baru):
        try:
            os.remove(_pending_path(program_path))
        except Exception:
            pass
        return False
    try:
        h = hashlib.sha256()
        with open(baru, "rb") as f:
            for blok in iter(lambda: f.read(1 << 20), b""):
                h.update(blok)
        sah = (not info.get("sha256")) or h.hexdigest() == info["sha256"]
    except Exception:
        sah = False
    if not sah:
        clear_pending(program_path)
        return False
    # PENGAMAT VERSI BASI (kasus nyata 12 Nov 2026): .new.exe + pending
    # sisa uji pagi hari di-apply ulang jam 10:11 saat app dari folder
    # yang sama diluncurkan lagi - app BALIK ke versi lama tanpa jejak
    # (user melihat popover versi lama + tombol restart hilang). Pending
    # yang versinya <= versi yang sedang jalan = buang. Hanya utk exe
    # frozen - mode dev bebas uji versi lama (file tetap utuh utk ganti
    # manual, kontrak uji _test_net).
    if getattr(sys, "frozen", False):
        try:
            from gui.theme import APP_VERSION as ver_kini
            if _ver_tuple(info.get("version", "")) <= _ver_tuple(ver_kini):
                clear_pending(program_path)
                try:
                    os.remove(baru)
                except Exception:
                    pass
                return False
        except Exception:
            pass
    return apply_update_and_restart(program_path)


def bersihkan_duplikat(program_path, log=None):
    """Buang exe TypingBot* duplikat di folder app - sisa download
    browser ('TypingBot (2).exe', 'TypingBot - Copy.exe' dll; keluhan
    live: teman user punya banyak typingbot exe, updatenya kacau).
    Kecuali: exe yang sedang jalan + 'TypingBot.exe' kanonik. Yang
    terkunci (= lagi jalan) otomatis dilewati - aman."""
    folder = os.path.dirname(os.path.abspath(program_path))
    kecuali = {os.path.basename(program_path).lower(), "typingbot.exe"}
    try:
        daftar = os.listdir(folder)
    except Exception:
        return
    for f in daftar:
        low = f.lower()
        if not low.endswith(".exe") or not low.startswith("typingbot"):
            continue
        if low in kecuali or low.endswith((".new.exe", ".lama.exe")):
            continue    # .new/.lama ditangani sweep lain
        try:
            os.remove(os.path.join(folder, f))
            if log:
                log(f"[BERSIH] duplikat dibuang: {f}")
        except OSError:
            pass        # terkunci = instance lain hidup - biarkan
        except Exception:
            pass
