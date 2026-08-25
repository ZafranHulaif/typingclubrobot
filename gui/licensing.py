"""Aktivasi: fingerprint mesin + kunci HMAC."""

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

from .theme import LICENSE_FILE



# Secret penandatanganan lisensi. Nilai asli ada di _license_secret.py
# (di-gitignore) supaya tidak ikut terekspos kalau kode dibuat publik.
try:
    from _license_secret import LICENSE_SECRET
except ImportError:
    LICENSE_SECRET = "DEV-ONLY-BUKAN-SECRET-ASLI"




# ------------------------------------------------------------------ lisensi
def _norm(s):
    return "".join(ch for ch in str(s).upper() if ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")




def _data_mesin():
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




def _kode_mesin():
    dig = hashlib.sha256(_data_mesin().encode("utf-8")).digest()
    kode = base64.b32encode(dig).decode("ascii")[:10]
    return "-".join([kode[:5], kode[5:]])




def _buat_kunci(kode_mesin):
    dig = hmac.new(LICENSE_SECRET.encode("utf-8"),
                   _norm(kode_mesin).encode("utf-8"), hashlib.sha256).digest()
    b32 = base64.b32encode(dig).decode("ascii")[:20]
    return "-".join(b32[i:i + 5] for i in range(0, 20, 5))




def _lisensi_tersimpan():
    try:
        return open(LICENSE_FILE, encoding="utf-8").read().strip()
    except Exception:
        return ""




def _lisensi_valid():
    return _norm(_lisensi_tersimpan()) == _norm(_buat_kunci(_kode_mesin()))




def _simpan_lisensi(kunci):
    with open(LICENSE_FILE, "w", encoding="utf-8") as f:
        f.write(kunci.strip() + "\n")
