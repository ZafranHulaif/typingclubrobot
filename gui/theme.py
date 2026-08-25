"""Palet warna, branding, dan path file."""

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

"""
bot_gui.py - Antarmuka grafis untuk TypingClub Autopilot.

Fitur:
- Tombol Start/Pause/Stop, pilihan browser + kecepatan, kartu aktivitas
  (kalimat besar bahasa awam; TANPA log di layar, TANPA istilah teknis).
- Dialog visual (bukan messagebox polos): kartu pilihan browser dengan logo
  asli dari file exe browser, konfirmasi buka browser / tutup aplikasi.
- Lisensi terikat mesin: aktivasi sekali per komputer (lihat _license_gen.py).
- Jendela Dev (tersembunyi, klik teks versi 5x): identitas build, bot.log.
"""



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



if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    PROGRAM_PATH = sys.executable
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    PROGRAM_PATH = os.path.abspath(__file__)



LOG_FILE = os.path.join(BASE_DIR, "bot.log")


SETTINGS_FILE = os.path.join(BASE_DIR, "typingbot_settings.json")


LICENSE_FILE = os.path.join(BASE_DIR, "license.dat")



APP_VERSION = "2.6"


PEMBUAT = "ZafranHulaif"



# ---------------------------------------------------------------- palet warna
BG = "#141519"          # latar jendela


PANEL = "#1b1d23"       # panel / dialog


CARD = "#20232b"        # kartu / tombol sekunder


CARD_HOVER = "#272b35"


EDGE = "#2c303b"        # garis pemisah / border


FG = "#e9eaee"


DIM = "#9aa0ab"


FAINT = "#6a7080"


ACCENT = "#4f8cff"


GREEN = "#3ecf6e"


YELLOW = "#e8b339"


RED = "#e05555"


ORANGE = "#ff9f43"


BTN_FG = "#101116"



BROWSER_WARNA = {"Brave": "#fb542b", "Chrome": "#4285f4", "Edge": "#0f7eb6"}




def _build_stamp():
    """Identitas build = tanggal modifikasi file exe/skrip sendiri."""
    try:
        return time.strftime("%d %b %Y %H:%M",
                             time.localtime(os.path.getmtime(PROGRAM_PATH)))
    except Exception:
        return "?"
