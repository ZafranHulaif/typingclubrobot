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

import paths



LOGIN_URL_INDIVIDUAL = "https://www.edclub.com/signin"   # Individual Edition

LOGIN_URL_SCHOOL = "https://sportal.edclub.com/"      # akun sekolah (Google)

SPEEDS = [(140, "NORMAL (140 wpm)"), (200, "CEPAT (200 wpm)"), (85, "SANTAI (85 wpm)"),
          # Tangga lebih cepat (permintaan user: dulu dicap 200 karena
          # situs LAMA layar putih kalau lebih cepat; coba lagi di UI baru
          # Nov 2026 - mesin pemulihan reload kini menutup kasus blank).
          (225, "KILAT (225 wpm)"), (250, "NGEBUT (250 wpm)"),
          (275, "GILA (275 wpm)"), (300, "MAKSIMAL (300 wpm)"),
          # 400: kompensasi overhead type_burst mengukur jeda nyata per
          # tombol (EMA) - setting = laju akhir, angka tinggi tetap
          # JUJUR terukur; normalisasi dur laporan tetap bikin ritme
          # tampak manusiawi (skor sah, layar skor muncul).
          (400, "PARANORMAL (400 wpm)")]


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

# Daftar lesson TAMPILAN BARU (dipakai navigasi yang TERLIHAT user -
# dulu _wait_daftar pergi ke LIST_URL tampilan lama = kedipan lama->
# baru + reload dobel, keluhan user Nov 2026: 'jangan pakai yang lama')
COURSE_URL = "https://www.edclub.com/student/course/3"

# Modal 'When is your birthday?' edclub (update UI student Nov 2026):
# muncul sekali per akun dan menahan semua lesson sampai diisi. Diisi
# tanggal netral dewasa supaya fitur akun tidak terkunci; ganti di sini
# kalau mau tanggal lain (bisa diubah lagi dari Settings edclub).
BIRTH_MONTH = "January"
BIRTH_YEAR = "2000"

try:
    # saat di-bundle jadi .exe, __file__ menunjuk folder temp PyInstaller
    # yang dihapus saat program keluar -> pakai lokasi .exe sendiri.
    _BASE = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
             else os.path.dirname(os.path.abspath(__file__)))
except Exception:
    _BASE = os.path.dirname(os.path.abspath(__file__))

_LOG_PATH = paths.data_path("bot.log")
_LEVEL_MAP_FILE = paths.data_path("level_map.json")

