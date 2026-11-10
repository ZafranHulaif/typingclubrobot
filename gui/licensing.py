"""Aktivasi: fingerprint mesin + kunci HMAC + lisensi online."""

import base64
import ctypes
import hashlib
import hmac
import json
import os
import queue
import re
import socket
import sys
import threading
import time
import tkinter as tk
import uuid
import zlib
from ctypes import wintypes
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from net import license as _netlic

from .theme import LICENSE_FILE

# ---- SIMULASI PENGGUNA BARU (env TYPINGBOT_BARU=1) ----
# Aman terhadap lisensi asli: file tidak dibaca, tidak ditulis, tidak
# dihapus. Mesin dilaporkan acak per run -> server melihat pelanggan
# baru betulan tiap simulasi.
_SIM_BARU = os.environ.get("TYPINGBOT_BARU") == "1"
_SIM_KODE = ""
if _SIM_BARU:
    _SIM_KODE = "SIM-" + base64.b32encode(os.urandom(4)).decode(
        "ascii").replace("=", "")[:6]



# Secret penandatanganan lisensi. Nilai asli ada di _license_secret.py
# (di-gitignore) supaya tidak ikut terekspos kalau kode dibuat publik.
try:
    from _license_secret import LICENSE_SECRET
except ImportError:
    LICENSE_SECRET = "DEV-ONLY-BUKAN-SECRET-ASLI"




# ------------------------------------------------------------------ lisensi
def _norm(s):
    return "".join(ch for ch in str(s).upper() if ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")




def _machine_data():
    """Sidik jari komputer: MAC + nama komputer + serial volume sistem."""
    bagian = []
    nic = uuid.getnode()
    if nic and not (nic & 0x010000000000):      # bit multicast = mac acak
        bagian.append(f"mac={nic:012x}")
    bagian.append("host=" + (os.environ.get("COMPUTERNAME")
                             or socket.gethostname()).upper())
    try:
        vol = wintypes.DWORD()
        drive = os.environ.get("SystemDrive", "C:") + "\\"
        if ctypes.windll.kernel32.GetVolumeInformationW(
                drive, None, 0, ctypes.byref(vol), None, None, None, 0):
            bagian.append(f"vol={vol.value}")
    except Exception:
        pass
    return "|".join(bagian)




def _machine_code():
    if _SIM_BARU:
        return _SIM_KODE     # mesin acak = pelanggan baru betulan
    dig = hashlib.sha256(_machine_data().encode("utf-8")).digest()
    kode = base64.b32encode(dig).decode("ascii")[:10]
    return "-".join([kode[:5], kode[5:]])




def _make_key(kode_mesin):
    dig = hmac.new(LICENSE_SECRET.encode("utf-8"),
                   _norm(kode_mesin).encode("utf-8"), hashlib.sha256).digest()
    b32 = base64.b32encode(dig).decode("ascii")[:20]
    return "-".join(b32[i:i + 5] for i in range(0, 20, 5))




def _saved_license():
    try:
        return open(LICENSE_FILE, encoding="utf-8").read().strip()
    except Exception:
        return ""




def _load_online_token():
    if _SIM_BARU:
        return None          # simulasi: token asli diabaikan
    return _netlic.load_token(LICENSE_FILE)




def _save_online_token(tok):
    if _SIM_BARU:
        return               # simulasi: jangan timpa lisensi asli
    _netlic.save_token(LICENSE_FILE, tok)




def _delete_online_token():
    """Hapus token lokal (mis. dicabut server) supaya state bersih."""
    if _SIM_BARU:
        return               # simulasi: lisensi asli kebal
    try:
        os.remove(LICENSE_FILE)
    except Exception:
        pass




def _license_valid():
    if _SIM_BARU:
        return False         # simulasi: selalu 'belum aktivasi'
    # dua format file: kunci lama (teks) atau token online (satu baris JSON)
    if _saved_license().startswith("{"):
        tok = _load_online_token()
        return bool(tok and _netlic.verify_token(tok))
    return _norm(_saved_license()) == _norm(_make_key(_machine_code()))




def _save_license(kunci):
    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
        f.write(kunci.strip() + "\n")
