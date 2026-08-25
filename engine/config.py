"""Konstanta: kandidat browser, kecepatan, URL, path."""

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



LOGIN_URL_INDIVIDUAL = "https://www.edclub.com/signin"   # Individual Edition

LOGIN_URL_SCHOOL = "https://sportal.edclub.com/"      # akun sekolah (Google)

SPEEDS = [(140, "NORMAL (140 wpm)"), (200, "CEPAT (200 wpm)"), (85, "SANTAI (85 wpm)")]


# Browser bawaan Chromium apa pun bisa. Urutan preferensi: Brave (yang
# dipakai selama pengembangan) -> Chrome -> Edge (bawaan Windows, jadi
# teman yang tidak install apa pun tetap bisa pakai).
# Override manual: set env TYPINGBOT_BROWSER=path\ke\browser.exe
BROWSER_CANDIDATES = [
    {"name": "Brave", "proc": "brave.exe", "paths": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ]},
    {"name": "Chrome", "proc": "chrome.exe", "paths": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]},
    {"name": "Edge", "proc": "msedge.exe", "paths": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]},
]

OCR_MIN_INTERVAL = 3.0       # jeda minimal antar percobaan OCR


try:
    import winocr
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False


UI_WORDS = {
    "settings", "setting", "account", "profile", "dashboard", "school", "class",
    "teacher", "student", "lesson", "unit", "level", "levels", "score", "wpm",
    "accuracy", "akurasi", "kecepatan", "practice", "review", "test", "speed",
    "next", "continue", "lanjut", "mulai", "play", "start", "begin", "pause",
    "menu", "back", "restart", "exit", "sound", "music", "help", "premium",
    "upgrade", "langganan", "berlangganan", "skip", "lewati", "close", "tutup",
    "ok", "okay", "cancel", "batal", "save", "simpan", "brave", "edclub",
    "typingclub", "typing", "club", "live", "progress", "progres", "sign",
    "login", "logout", "search", "cari", "home", "beranda", "end", "fin",
}



LIST_URL = "https://www.edclub.com/sportal/program-3.game"

try:
    # saat di-bundle jadi .exe, __file__ menunjuk folder temp PyInstaller
    # yang dihapus saat program keluar -> pakai lokasi .exe sendiri.
    _BASE = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
             else os.path.dirname(os.path.abspath(__file__)))
except Exception:
    _BASE = os.path.dirname(os.path.abspath(__file__))

_LOG_PATH = os.path.join(_BASE, "bot.log")
_LEVEL_MAP_FILE = os.path.join(_BASE, "level_map.json")

