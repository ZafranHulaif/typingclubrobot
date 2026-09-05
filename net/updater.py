"""Pembaruan mandiri: cek versi, unduh, verifikasi hash, tukar exe.

Tukar exe hanya berlaku untuk hasil build PyInstaller (frozen); saat
dijalankan dari sumber, file baru diunduh dan user mengganti manual.
"""

import os
import subprocess
import sys

from . import api
from .license import download_param

NEW_SUFFIX = ".new.exe"
CMD_NAME = "_update.cmd"


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
    """
    url = "/api/download?t=" + download_param(tok)

    def prog(got, total, _cb=progress_cb):
        if _cb:
            _cb(got, total or info.get("size"))

    digest = api.http_download(url, new_path, prog)
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
        'if exist "%EXE%" start "" "%EXE%"\r\n'
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
