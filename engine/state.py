"""State global yang bisa berubah lintas modul.
Semua akses dari modul lain: `from . import state` lalu
`state.STOP` dst - attribute module selalu live."""

import ctypes
import io
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from .config import BROWSER_CANDIDATES

import level_data as _level_data




# ---------------------------------------------------------------------------
# Kontrol: hotkey global (F9 pause, F10 kecepatan, F11 stop)
# ---------------------------------------------------------------------------

PAUSED = False

STOP = False

PERLU_LOGIN = False      # True = sesi edclub mati; GUI memunculkan popup login

MINTA_LOGIN_NAV = False   # GUI meminta bot membuka halaman login edclub

MINTA_LOGIN_URL = ""      # URL login pilihan GUI (individu / sekolah)

LOGIN_DICEK = False       # True setelah patroli login berjalan minimal 1x

TUNGGU_RENTANG = False    # True = GUI sedang menanya rentang; bot menunggu

MINTA_BANGUN_PETA = False # GUI meminta bot membangun peta level lengkap

RENTANG_SELESAI = False   # True = mencapai level akhir rentang pilihan user

LEVEL_START = 1           # rentang level pilihan user (GUI)

LEVEL_END = 0             # 0 = tanpa batas akhir

RENTANG_SIAP = False      # True setelah user menjawab dialog rentang di Start

MENUNGGU_SETUP = False    # True = menunggu user menyelesaikan set-up first-run browser

HOTKEY_AKTIF = True       # False = F9/F10/F11 diabaikan (toggle GUI)

SPEED_IDX = 0

BROWSER = None   # kandidat terpilih: {"name":..,"exe":..,"proc":..}

FORCE_BROWSER = ""   # path exe pilihan user (GUI); kosong = otomatis

LAST_BROWSER = ""    # path exe browser terakhir yang benar2 dipakai (preferensi Otomatis)

BRAVE_BINARY = BROWSER_CANDIDATES[0]["paths"][0]   # (kompatibilitas lama)

DEDICATED_PROFILE = os.path.expandvars(r"%LOCALAPPDATA%\TypingBot\profile")

# Mode profil: "bot" = profil khusus terpisah (default, aman) | "saya" =
# pakai profil asli milik user pilihan sendiri (login/bookmark ikut terpakai).
# Chrome/Edge 136+ menolak mode debug di folder data aslinya, tetapi masih
# mengizinkan kalau folder itu dibuka lewat junction (path lain -> data sama;
# teruji di Chrome/Edge 151). Brave menerima folder asli langsung.
PROFILE_MODE = "bot"

PROFILE_DIR = ""       # 'Default' / 'Profile 1' / ... (mode 'saya')

PROFILE_LABEL = ""     # nama tampilan profil utk pesan ramah (mis. 'Student')

# Port debug bisa berubah saat runtime: kalau 9222 kebetulan dipakai
# aplikasi lain (widget sistem bawaan laptop, WebView milik Adobe dll.),
# bot cukup memakai port berikutnya - aplikasi itu tidak perlu ditutup.
DEBUG_PORT = 9222



# Konfirmasi penutupan paksa aplikasi (dipasang GUI agar pakai dialog, bukan
# console). Default: tanya via console input.
_confirmer = None



pw = None

browser = None

PAGE = None

STATUS_URL = ""   # dibaca GUI (string biasa, aman lintas thread)

STATUS_LABEL = ""  # label level asli dari halaman (mis. 'L87')

_label_retry = 0.0

_rentang_nav = 0.0

_rentang_jump_done = False

_rentang_max_seen = 0    # level tertinggi yang terlihat sesi ini (anti lompat-balik)

_unlock_set = None    # level terbuka di akun (diisi saat perlu)

_last_loop_err = 0.0


_repeat_click = {"label": "", "count": 0, "until": 0.0}



_loop_overhead = 0.030   # estimasi overhead verifikasi per karakter (ewma)

_last_char_delay = 0.0


_user_watch_cache = {"t": 0.0, "elapsed": 1e9}

_user_note = {"tunda": False}



_tunggu_user_since = {"url": "", "t": 0.0}

MINTA_TANYA_LANJUT = False   # GUI: popup 'masih menunggu?' setelah 2 menit



_enter_times = []



_std_last_rem = None

_std_attempts = 0

_stall_user_note = False



# ---------------------------------------------------------------------------
# Tutorial boxed
# ---------------------------------------------------------------------------

_tut_sig = None

_tut_attempts = 0


_tut_pending_sig = None



_tut_full = None



# ---------------------------------------------------------------------------
# Minigame DOM
# ---------------------------------------------------------------------------

_last_focus_click = {}


_phaser_cooldown = {"until": 0.0}

_phaser_freeze = {"url": "", "count": 0, "clicked": False}


last_hold_raw = ""

hold_attempts = 0



_scrkey = {"key": "", "count": 0, "until": 0.0}


_intro_sig = None

_intro_attempts = 0

_intro_flow = False   # True = alur intro berjalan (f->j->d->k di level yang sama)



# ---------------------------------------------------------------------------
# Fallback OCR canvas (non-Phaser)
# ---------------------------------------------------------------------------

last_ocr_time = 0.0

_last_recovery = 0.0

# Berapa kali lesson URL ini sudah di-recovery (guard anti loop level rusak)
_recovery_counts = {}



_hijack_counts = {}

_broken_lessons = set()



_level_label_cache = {}

_level_map = {str(n): f"https://www.edclub.com/sportal/program-3/{i}.play"
             for n, i in _level_data.PETA.items()}


# Balik peta: id URL -> nomor level (untuk indikator GUI instan).
_url_ke_level = {}



# Dialog 'level terkunci' bot<->GUI: bot menunggu jawaban user.
LEVEL_TANYA = {"aktif": False, "start": 0, "fallback": 0, "jawab": "", "event": None}

_rentang_validasi_done = False



# ---------------------------------------------------------------------------
# Loop utama
# ---------------------------------------------------------------------------

last_typed_text = ""

last_action_time = time.time()

last_debug_dump = 0.0

last_url = ""

_premlock_since = 0.0

_login_notice = 0.0



# ---------------------------------------------------------------------------
# Deteksi sesi login edclub
#
# Tiga lapis (tanpa menebak selector DOM yang tidak terverifikasi):
# 1. URL login/signin (perilaku lama, tetap).
# 2. Sentinel 401/403: pasang listener respons jaringan sekali di connect().
# edclub sendiri yang "mengetahui" sesi mati lewat API-nya (ini satu-
# satunya cara menangkap kasus "logout diam-diam saat tab lama dibiarkan
# terbuka" - cookie masih ada tapi server sudah menolaknya).
# 3. Cookie sesi via CDP: profil yang belum pernah login tidak punya cookie
# edclub selain milik Cloudflare (__cf_bm/_cfuvid) -> jelas belum login.
# ---------------------------------------------------------------------------
_login_sentinel = {"ok": True, "alasan": "", "gagal403": 0.0,
                   "terakhir401": 0.0, "path401": {}, "log401": 0.0,
                   "pernah_in": False, "unknown_mulai": 0.0}

_login_ck = {"terakhir": 0.0}



_probe_tab_ck = {"terakhir": 0.0}

_stripe_sweep_last = 0.0

_nav_try = 0.0

stats = {"std": 0, "mini": 0, "ocr": 0, "popup": 0, "hold": 0, "uikey": 0, "tut": 0,
         "phaser": 0, "video": 0, "intro": 0}

