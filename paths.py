"""Lokasi file data user + pintasan Start Menu.

Saat dibundel jadi .exe: semua file data (lisensi, pengaturan, peta
level, log) hidup di %LOCALAPPDATA%/TypingBot supaya folder tempat exe
berada tetap bersih, hanya satu file exe (keluhan: exe meninggalkan
4-5 file di sebelahnya). Saat dev: tetap di folder repo. File data lama
di sebelah exe dipindah otomatis sekali di awal (migrasi).
"""

import os
import shutil
import subprocess
import sys

_DATA_FILES = ("license.dat", "license.dat.bak", "typingbot_settings.json",
               "level_map.json", "server_url.txt")
_migrated = False


def exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    global _migrated
    if getattr(sys, "frozen", False):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "TypingBot")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            return exe_dir()
        if not _migrated:
            _migrated = True
            _migrate(d)
        return d
    return exe_dir()


def _migrate(d):
    """Pindahkan file data lama di sebelah exe (versi < 2.9.23)."""
    for nama in _DATA_FILES:
        lama = os.path.join(exe_dir(), nama)
        baru = os.path.join(d, nama)
        try:
            if os.path.exists(lama) and not os.path.exists(baru):
                shutil.move(lama, baru)
        except Exception:
            pass
    # log lama di sebelah exe = sampah - hapus; log baru ditulis di
    # folder data
    try:
        lama = os.path.join(exe_dir(), "bot.log")
        if os.path.exists(lama):
            os.remove(lama)
    except Exception:
        pass


def data_path(nama):
    return os.path.join(data_dir(), nama)


def ensure_start_menu_shortcut():
    """Buat pintasan 'TypingBot' di Start Menu (frozen saja) supaya
    aplikasi bisa dicari dari menu Start tanpa installer. Aman dipanggil
    berulang: pintasan yang sudah ada dibiarkan."""
    if not getattr(sys, "frozen", False):
        return
    try:
        sm = os.path.join(
            os.environ.get("APPDATA") or os.path.expanduser("~"),
            "Microsoft", "Windows", "Start Menu", "Programs")
        os.makedirs(sm, exist_ok=True)
        lnk = os.path.join(sm, "TypingBot.lnk")
        if os.path.exists(lnk):
            return
        exe = sys.executable
        ps = ("$s=(New-Object -ComObject WScript.Shell)"
              f".CreateShortcut('{lnk}');"
              f"$s.TargetPath='{exe}';"
              f"$s.WorkingDirectory='{os.path.dirname(exe)}';"
              f"$s.IconLocation='{exe},0';$s.Save()")
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", ps],
            creationflags=0x08000000, timeout=20,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
