"""Pembaruan mandiri: cek versi, unduh, verifikasi hash, tukar exe.

Tukar exe hanya berlaku untuk hasil build PyInstaller (frozen); saat
dijalankan dari sumber, file baru diunduh dan user mengganti manual.
"""

import hashlib
import json
import os
import subprocess
import sys

from . import api
from .license import download_param

NEW_SUFFIX = ".new.exe"
CMD_NAME = "_update.cmd"
PENDING_NAME = "update_pending.json"


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
    isi = (
        "@echo off\r\n"
        "setlocal\r\n"
        'set EXE="%~dp0' + nama + '"\r\n'
        'set NEW="%~dp0' + nama + NEW_SUFFIX + '"\r\n'
        "set /a N=0\r\n"
        ":wait\r\n"
        "timeout /t 1 /nobreak >nul\r\n"
        'del /f /q "%EXE%" >nul 2>&1\r\n'
        'if not exist "%EXE%" goto moved\r\n'
        "set /a N+=1\r\n"
        "if %N% lss 30 goto wait\r\n"
        "exit /b 1\r\n"
        ":moved\r\n"
        'if not exist "%NEW%" exit /b 1\r\n'
        'move /y "%NEW%" "%EXE%" >nul 2>&1\r\n'
        # luncurkan lewat explorer = seperti klik ganda user; 'start'
        # dari cmd menjadikan cmd orang tua proses dan ditolak lapisan
        # keamanan Windows ("security validation failure")
        'if exist "%EXE%" explorer "%EXE%"\r\n'
        'del /f /q "%~f0" >nul 2>&1\r\n'
    )
    with open(cmd, "w", encoding="ascii", newline="") as f:
        f.write(isi)
    flags = 0x00000008
    try:
        flags |= 0x00000200
    except Exception:
        pass
    subprocess.Popen(["cmd", "/c", CMD_NAME], cwd=folder,
                     creationflags=flags, close_fds=True)
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
    for p in (_pending_path(program_path), program_path + NEW_SUFFIX):
        try:
            os.remove(p)
        except Exception:
            pass


def pop_pending(program_path):
    """Dipanggil SEBELUM GUI saat aplikasi mulai.

    True = proses tukar sedang berjalan (pemanggil wajib keluar segera;
    script kemudian menjalankan versi baru). Marker/unduhan basi
    (hilang atau hash tidak cocok) dibersihkan diam-diam.
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
    return apply_update_and_restart(program_path)
